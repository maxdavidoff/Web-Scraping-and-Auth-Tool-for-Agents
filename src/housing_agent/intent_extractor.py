from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace
from datetime import date
from typing import Any, Mapping, Protocol, Sequence

from .llm_client import DEFAULT_MISTRAL_MODEL, MistralChatClient
from .location_scope import is_neighborhood_only_location
from .query_planner import plan_query
from .types import HousingSearchIntent, QueryPlan


class JsonChatClient(Protocol):
    model: str

    def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1200,
    ) -> str:
        ...


@dataclass(frozen=True)
class IntentExtractionResult:
    intent: HousingSearchIntent
    query_plan: QueryPlan
    raw_response: Mapping[str, Any]
    model: str


INTENT_SYSTEM_PROMPT = """
You extract provider-neutral housing search intent for a rental-search planner.

Return exactly one JSON object. Do not choose providers and do not mention scraping.
Use null for unknown scalar values, false for unknown booleans, and [] for unknown lists.

Allowed keys:
location, neighborhoods, avoid_neighborhoods, min_price, max_price,
price_basis, bedrooms, bedroom_min, bedroom_max, bathrooms,
bathroom_min, property_types, type_of_places, pet_policy, pet_policy_negated, furnished,
move_in_date, move_out_date, lease_length, campus_or_school,
commute_target, max_commute_minutes, roommate_count, amenities,
required_amenities, preferred_amenities, dealbreakers, safety_priority,
student_priority, sort, map_bounds, photos,
verified_listings, featured, page, section8, income_restricted,
wheelchair_accessible, utilities_included, washer_dryer, keyword,
intent_kind, flexibility_notes, notes.

Field guidance:
- location should be the larger city or metro area to search. Do not use a neighborhood, campus, building, or small area as location.
- Preserve neighborhood preferences in neighborhoods and areas the user wants to avoid in avoid_neighborhoods. Provider searches are city-wide, so neighborhoods are not initial source filters.
- If the user gives a neighborhood together with a larger city, keep the larger city in location and put the neighborhood in neighborhoods.
- If the user gives only a neighborhood, campus, or small area and no larger city can be reasonably inferred, leave location null so the agent can ask for the larger city.
- For campus searches, fill campus_or_school and infer a practical larger city only when obvious, but do not turn the request into all property_types unless the user explicitly says they are open to all property types.
- For summer programs, summer internships, semesters, or sublets, set intent_kind to student_sublet when appropriate and preserve timing in move dates, lease_length, or notes.
- roommate_count is the number of roommates the user plans to live with. Use 0 for living alone, 1 for one roommate, and 2+ for multiple roommates or a group rental.
- If the user is looking for a full rental with multiple roommates, set intent_kind to general_rental unless affordable/voucher signals are explicit.
- If the user is looking just for themself, a private room, a shared room, or a solo sublet, preserve that with roommate_count and/or type_of_places.
- bedrooms is the apartment's total bedroom count. Do not infer bedrooms=1 from type_of_places=["Private room"]; leave bedrooms null for private/shared room searches unless the user gives an explicit apartment size.
- If the user says they do not know budget, room type, or timing, preserve that uncertainty in flexibility_notes instead of fabricating a value.
- Dates should be ISO-like YYYY-MM-DD when a specific date is clear; otherwise preserve useful timing in notes.
- property_types can include Apartment, House, Townhouse, Condo.
- type_of_places can include Private room, Shared room, Entire place.
- pet_policy should preserve positive pet constraints like dogs, cats, pet friendly. Put negated pet constraints like no pets, no dogs, no cats, without pets in pet_policy_negated instead of pet_policy.
- furnished is true only when explicitly requested, false only when explicitly unfurnished, otherwise null.
- Put must-have amenities in required_amenities and nice-to-have amenities in preferred_amenities.
- price_basis should be one of total, per_person, per_room, unknown.
- safety_priority and student_priority should be low, medium, high, or unknown.
- section8, income_restricted, wheelchair_accessible, utilities_included, washer_dryer are true only when explicit.
- intent_kind should be one of student_sublet, general_rental, affordable, apartment, unknown.
- notes should preserve constraints that do not fit cleanly into fields.
""".strip()


INTENT_UPDATE_SYSTEM_PROMPT = """
You update provider-neutral housing search intent for a rental-search planner.

Return exactly one JSON object containing the full merged HousingSearchIntent.
Preserve previous values unless the latest user message changes, corrects, or negates them.
Newer user messages override older values.

Use null for unknown scalar values, false for unknown booleans, and [] for unknown lists.
Do not choose providers, build URLs, mention scraping, emit browser settings, or output commands.

Allowed keys:
location, neighborhoods, avoid_neighborhoods, min_price, max_price,
price_basis, bedrooms, bedroom_min, bedroom_max, bathrooms,
bathroom_min, property_types, type_of_places, pet_policy, pet_policy_negated, furnished,
move_in_date, move_out_date, lease_length, campus_or_school,
commute_target, max_commute_minutes, roommate_count, amenities,
required_amenities, preferred_amenities, dealbreakers, safety_priority,
student_priority, sort, map_bounds, photos,
verified_listings, featured, page, section8, income_restricted,
wheelchair_accessible, utilities_included, washer_dryer, keyword,
intent_kind, flexibility_notes, notes.

Field guidance:
- location should be the larger city or metro area to search. Do not use a neighborhood, campus, building, or small area as location.
- Preserve neighborhood preferences in neighborhoods and areas the user wants to avoid in avoid_neighborhoods. Provider searches are city-wide, so neighborhoods are not initial source filters.
- If the latest message gives a neighborhood or area preference but the previous intent already has a larger city, preserve the previous city in location and put the neighborhood in neighborhoods.
- If the latest message gives only a neighborhood, campus, or small area and no larger city can be reasonably inferred, leave location null so the agent can ask for the larger city.
- For campus searches, fill campus_or_school and infer a practical larger city only when obvious, but do not turn the request into all property_types unless the user explicitly says they are open to all property types.
- For summer programs, summer internships, semesters, or sublets, set intent_kind to student_sublet when appropriate and preserve timing in move dates, lease_length, or notes.
- roommate_count is the number of roommates the user plans to live with. Use 0 for living alone, 1 for one roommate, and 2+ for multiple roommates or a group rental.
- If the user is looking for a full rental with multiple roommates, set intent_kind to general_rental unless affordable/voucher signals are explicit.
- If the user is looking just for themself, a private room, a shared room, or a solo sublet, preserve that with roommate_count and/or type_of_places.
- bedrooms is the apartment's total bedroom count. Do not infer bedrooms=1 from type_of_places=["Private room"]; leave bedrooms null for private/shared room searches unless the user gives an explicit apartment size.
- If the user says they do not know budget, room type, or timing, preserve that uncertainty in flexibility_notes instead of fabricating a value.
- Dates should be ISO-like YYYY-MM-DD when a specific date is clear; otherwise preserve useful timing in notes.
- property_types can include Apartment, House, Townhouse, Condo.
- type_of_places can include Private room, Shared room, Entire place.
- pet_policy should preserve positive pet constraints like dogs, cats, pet friendly. Put negated pet constraints like no pets, no dogs, no cats, without pets in pet_policy_negated instead of pet_policy.
- furnished is true only when explicitly requested, false only when explicitly unfurnished, otherwise null.
- Put must-have amenities in required_amenities and nice-to-have amenities in preferred_amenities.
- price_basis should be one of total, per_person, per_room, unknown.
- safety_priority and student_priority should be low, medium, high, or unknown.
- section8, income_restricted, wheelchair_accessible, utilities_included, washer_dryer are true only when explicit.
- intent_kind should be one of student_sublet, general_rental, affordable, apartment, unknown.
- notes should preserve constraints that do not fit cleanly into fields.
""".strip()


def build_intent_messages(user_request: str, *, today: str | None = None) -> list[dict[str, str]]:
    request = user_request.strip()
    if not request:
        raise ValueError("Housing request cannot be empty.")

    effective_today = today or date.today().isoformat()
    return [
        {"role": "system", "content": INTENT_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "today": effective_today,
                    "housing_request": request,
                },
                ensure_ascii=False,
            ),
        },
    ]


def build_intent_update_messages(
    previous_intent: HousingSearchIntent | Mapping[str, Any] | None,
    latest_user_message: str,
    *,
    transcript: Sequence[Mapping[str, str]] | None = None,
    today: str | None = None,
) -> list[dict[str, str]]:
    message = latest_user_message.strip()
    if not message:
        raise ValueError("Latest user message cannot be empty.")

    effective_today = today or date.today().isoformat()
    return [
        {"role": "system", "content": INTENT_UPDATE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "today": effective_today,
                    "previous_intent": _intent_payload(previous_intent),
                    "latest_user_message": message,
                    "transcript": list(transcript or []),
                },
                ensure_ascii=False,
            ),
        },
    ]


def extract_housing_intent(
    user_request: str,
    *,
    client: JsonChatClient | None = None,
    model: str | None = None,
    providers: Sequence[str] | None = None,
    today: str | None = None,
) -> IntentExtractionResult:
    chat_client = client or MistralChatClient.from_env(model=model)
    messages = build_intent_messages(user_request, today=today)
    response_text = chat_client.complete_json(messages, temperature=0.0, max_tokens=1200)
    raw = parse_json_object(response_text)
    intent = intent_from_mapping(raw)
    intent = _apply_location_scope_guards(intent)
    query_plan = plan_query(intent, providers=providers)
    return IntentExtractionResult(
        intent=intent,
        query_plan=query_plan,
        raw_response=raw,
        model=getattr(chat_client, "model", model or DEFAULT_MISTRAL_MODEL),
    )


def update_housing_intent(
    previous_intent: HousingSearchIntent | Mapping[str, Any] | None,
    latest_user_message: str,
    *,
    client: JsonChatClient | None = None,
    model: str | None = None,
    transcript: Sequence[Mapping[str, str]] | None = None,
    providers: Sequence[str] | None = None,
    today: str | None = None,
) -> IntentExtractionResult:
    chat_client = client or MistralChatClient.from_env(model=model)
    messages = build_intent_update_messages(
        previous_intent,
        latest_user_message,
        transcript=transcript,
        today=today,
    )
    response_text = chat_client.complete_json(messages, temperature=0.0, max_tokens=1200)
    raw = parse_json_object(response_text)
    previous = previous_intent if isinstance(previous_intent, HousingSearchIntent) else (
        intent_from_mapping(previous_intent) if previous_intent else None
    )
    intent = intent_from_mapping(raw)
    intent = _apply_location_scope_guards(intent, previous_intent=previous)
    query_plan = plan_query(intent, providers=providers)
    return IntentExtractionResult(
        intent=intent,
        query_plan=query_plan,
        raw_response=raw,
        model=getattr(chat_client, "model", model or DEFAULT_MISTRAL_MODEL),
    )


def _intent_payload(value: HousingSearchIntent | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, HousingSearchIntent):
        payload = asdict(value)
    else:
        payload = dict(value)
    return {
        key: list(item) if isinstance(item, tuple) else item
        for key, item in payload.items()
    }


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError("Intent extractor response must be a JSON object.")
    return value


def intent_from_mapping(data: Mapping[str, Any]) -> HousingSearchIntent:
    normalized = {
        "location": _optional_string(data.get("location")),
        "neighborhoods": _string_tuple(data.get("neighborhoods")),
        "avoid_neighborhoods": _string_tuple(data.get("avoid_neighborhoods")),
        "min_price": _optional_int(data.get("min_price")),
        "max_price": _optional_int(data.get("max_price")),
        "price_basis": _choice_string(data.get("price_basis"), {"total", "per_person", "per_room", "unknown"}, "unknown"),
        "bedrooms": _optional_int(data.get("bedrooms")),
        "bedroom_min": _optional_int(data.get("bedroom_min")),
        "bedroom_max": _optional_int(data.get("bedroom_max")),
        "bathrooms": _optional_float(data.get("bathrooms")),
        "bathroom_min": _optional_float(data.get("bathroom_min")),
        "property_types": _string_tuple(data.get("property_types")),
        "type_of_places": _string_tuple(data.get("type_of_places")),
        "pet_policy": (),
        "pet_policy_negated": (),
        "furnished": _optional_bool(data.get("furnished")),
        "move_in_date": _optional_string(data.get("move_in_date") or data.get("movein")),
        "move_out_date": _optional_string(data.get("move_out_date") or data.get("moveout")),
        "lease_length": _optional_string(data.get("lease_length")),
        "campus_or_school": _optional_string(data.get("campus_or_school")),
        "commute_target": _optional_string(data.get("commute_target")),
        "max_commute_minutes": _optional_int(data.get("max_commute_minutes")),
        "roommate_count": _optional_int(data.get("roommate_count")),
        "amenities": _string_tuple(data.get("amenities")),
        "required_amenities": _string_tuple(data.get("required_amenities")),
        "preferred_amenities": _string_tuple(data.get("preferred_amenities")),
        "dealbreakers": _string_tuple(data.get("dealbreakers")),
        "safety_priority": _choice_string(data.get("safety_priority"), {"low", "medium", "high", "unknown"}, "unknown"),
        "student_priority": _choice_string(data.get("student_priority"), {"low", "medium", "high", "unknown"}, "unknown"),
        "sort": _optional_string(data.get("sort")),
        "map_bounds": _map_bounds(data.get("map_bounds")),
        "photos": _bool(data.get("photos")),
        "verified_listings": _bool(data.get("verified_listings") or data.get("verified")),
        "featured": _bool(data.get("featured")),
        "page": _optional_int(data.get("page")),
        "section8": _bool(data.get("section8")),
        "income_restricted": _bool(data.get("income_restricted")),
        "wheelchair_accessible": _bool(data.get("wheelchair_accessible")),
        "utilities_included": _bool(data.get("utilities_included")),
        "washer_dryer": _bool(data.get("washer_dryer")),
        "keyword": _optional_string(data.get("keyword")),
        "intent_kind": _intent_kind(data.get("intent_kind")),
        "flexibility_notes": _string_tuple(data.get("flexibility_notes")),
        "notes": _string_tuple(data.get("notes")),
    }

    pet_policy, pet_policy_negated = _normalize_pet_policy(
        _string_tuple(data.get("pet_policy")),
        _string_tuple(data.get("pet_policy_negated")),
        normalized["notes"],
        normalized["flexibility_notes"],
    )
    normalized["pet_policy"] = pet_policy
    normalized["pet_policy_negated"] = pet_policy_negated

    furnished_status = _string_tuple(data.get("furnished_status"))
    if normalized["furnished"] is None and furnished_status:
        text = " ".join(furnished_status).lower()
        if "unfurnished" in text:
            normalized["furnished"] = False
        elif "furnished" in text or "move-in ready" in text:
            normalized["furnished"] = True

    return HousingSearchIntent(**normalized)


def _apply_location_scope_guards(
    intent: HousingSearchIntent,
    *,
    previous_intent: HousingSearchIntent | None = None,
) -> HousingSearchIntent:
    location = intent.location
    neighborhoods = intent.neighborhoods
    if is_neighborhood_only_location(location):
        neighborhoods = _merge_strings((location,), neighborhoods)
        location = previous_intent.location if previous_intent and previous_intent.location else None
    return replace(intent, location=location, neighborhoods=neighborhoods)


def _normalize_pet_policy(
    pet_policy: tuple[str, ...],
    pet_policy_negated: tuple[str, ...],
    notes: tuple[str, ...],
    flexibility_notes: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    positive: list[str] = []
    negated: list[str] = list(pet_policy_negated)
    for value in pet_policy:
        tokens = _pet_negation_tokens(value)
        if tokens:
            negated.extend(tokens)
        else:
            positive.append(value)

    text = " ".join([*notes, *flexibility_notes])
    negated.extend(_pet_negation_tokens(text))
    return _merge_strings(positive, ()), _merge_strings(negated, ())


def _pet_negation_tokens(text: str) -> tuple[str, ...]:
    normalized = str(text).lower()
    tokens: list[str] = []
    patterns = [
        ("dogs", ("no dogs", "without dogs")),
        ("cats", ("no cats", "without cats")),
        ("pets", ("no pets", "without pets", "pets prohibited", "not pet friendly")),
    ]
    for token, phrases in patterns:
        if any(phrase in normalized for phrase in phrases):
            tokens.append(token)
    return tuple(tokens)


def _merge_strings(left: Sequence[str], right: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in (*left, *right):
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            merged.append(text)
    return tuple(merged)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "unknown", "n/a"}:
        return None
    return text


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value: Any) -> bool:
    return bool(_optional_bool(value))


def _optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "on"}:
        return True
    if text in {"false", "no", "n", "0", "off"}:
        return False
    return None


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        values = list(value)
    else:
        values = [value]
    return tuple(str(item).strip() for item in values if str(item).strip())


def _map_bounds(value: Any) -> Mapping[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    bounds: dict[str, float] = {}
    for key in ("west", "south", "east", "north"):
        number = _optional_float(value.get(key))
        if number is not None:
            bounds[key] = number
    return bounds if len(bounds) == 4 else None


def _intent_kind(value: Any) -> str | None:
    text = _optional_string(value)
    if text in {"student_sublet", "general_rental", "affordable", "apartment", "unknown"}:
        return text
    return text or None


def _choice_string(value: Any, allowed: set[str], default: str) -> str:
    text = _optional_string(value)
    if not text:
        return default
    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default
