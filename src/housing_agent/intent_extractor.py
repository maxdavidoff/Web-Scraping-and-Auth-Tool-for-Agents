from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping, Protocol, Sequence

from .llm_client import DEFAULT_MISTRAL_MODEL, MistralChatClient
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
location, min_price, max_price, bedrooms, bedroom_min, bedroom_max, bathrooms,
bathroom_min, property_types, type_of_places, pet_policy, furnished,
move_in_date, move_out_date, amenities, sort, map_bounds, photos,
verified_listings, featured, page, section8, income_restricted,
wheelchair_accessible, utilities_included, washer_dryer, keyword,
intent_kind, notes.

Field guidance:
- location should be a city/neighborhood/campus area/ZIP as stated or reasonably inferred.
- Dates should be ISO-like YYYY-MM-DD when a specific date is clear; otherwise preserve useful timing in notes.
- property_types can include Apartment, House, Townhouse, Condo.
- type_of_places can include Private room, Shared room, Entire place.
- pet_policy should preserve explicit pet constraints like dogs, cats, pet friendly, no pets.
- furnished is true only when explicitly requested, false only when explicitly unfurnished, otherwise null.
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
location, min_price, max_price, bedrooms, bedroom_min, bedroom_max, bathrooms,
bathroom_min, property_types, type_of_places, pet_policy, furnished,
move_in_date, move_out_date, amenities, sort, map_bounds, photos,
verified_listings, featured, page, section8, income_restricted,
wheelchair_accessible, utilities_included, washer_dryer, keyword,
intent_kind, notes.

Field guidance:
- location should be a city/neighborhood/campus area/ZIP as stated or reasonably inferred.
- Dates should be ISO-like YYYY-MM-DD when a specific date is clear; otherwise preserve useful timing in notes.
- property_types can include Apartment, House, Townhouse, Condo.
- type_of_places can include Private room, Shared room, Entire place.
- pet_policy should preserve explicit pet constraints like dogs, cats, pet friendly, no pets.
- furnished is true only when explicitly requested, false only when explicitly unfurnished, otherwise null.
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
    intent = intent_from_mapping(raw)
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
        "min_price": _optional_int(data.get("min_price")),
        "max_price": _optional_int(data.get("max_price")),
        "bedrooms": _optional_int(data.get("bedrooms")),
        "bedroom_min": _optional_int(data.get("bedroom_min")),
        "bedroom_max": _optional_int(data.get("bedroom_max")),
        "bathrooms": _optional_float(data.get("bathrooms")),
        "bathroom_min": _optional_float(data.get("bathroom_min")),
        "property_types": _string_tuple(data.get("property_types")),
        "type_of_places": _string_tuple(data.get("type_of_places")),
        "pet_policy": _string_tuple(data.get("pet_policy")),
        "furnished": _optional_bool(data.get("furnished")),
        "move_in_date": _optional_string(data.get("move_in_date") or data.get("movein")),
        "move_out_date": _optional_string(data.get("move_out_date") or data.get("moveout")),
        "amenities": _string_tuple(data.get("amenities")),
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
        "notes": _string_tuple(data.get("notes")),
    }

    furnished_status = _string_tuple(data.get("furnished_status"))
    if normalized["furnished"] is None and furnished_status:
        text = " ".join(furnished_status).lower()
        if "unfurnished" in text:
            normalized["furnished"] = False
        elif "furnished" in text or "move-in ready" in text:
            normalized["furnished"] = True

    return HousingSearchIntent(**normalized)


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
