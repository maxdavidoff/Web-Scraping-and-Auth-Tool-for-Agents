from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from typing import Any, Mapping, Sequence

from .intent_extractor import JsonChatClient, parse_json_object
from .llm_client import DEFAULT_MISTRAL_MODEL, MistralChatClient
from .location_scope import asks_for_neighborhood_preference, is_neighborhood_only_location
from .types import HousingSearchIntent, SearchReadiness


READINESS_SYSTEM_PROMPT = """
You are a housing-search readiness evaluator.

Your job is to decide whether the current HousingSearchIntent contains enough information to run a useful property search and later recommend listings.

You do not choose providers, build URLs, mention scraping, output commands, or trigger execution.
Return exactly one JSON object.

Definitions:
- A hard constraint is a requirement that a listing must satisfy.
- A soft preference is useful for ranking but should not exclude listings unless the user says it is required.
- ready_to_search means there is enough information to run a broad search that is not obviously wasteful.
- ready_to_recommend means there is enough information to say that specific listings likely satisfy the user's needs.
- Ask at most two follow-up questions.
- Prefer searching over asking when missing information can be safely inferred or handled as a soft preference.
- Ask follow-up questions only when missing information would materially change the search.
- Do not ask for neighborhood preferences. The provider searches are city-wide, so neighborhoods are not initial search filters.
- If the user only supplied a neighborhood, campus area, or small area, ask for the larger city or metro area to search.
- If city is known but the housing type is vague, ask one routing question to distinguish:
  solo/private-room/sublet searches, full rentals for multiple roommates, and affordable/voucher/accessibility searches.
- If the user says they do not know a value, treat that value as flexible/unknown and move to the next most useful question instead of repeating the same question.
- Do not say all required fields are provided if you are returning followup_questions or next_action is ask_followup.

Minimum readiness rules:
For general rentals:
- Need location.
- Need either max_price or a clear affordability cue.
- Need bedrooms, bedroom_min, bedroom_max, type_of_places, or a clear flexible/browsing signal.
- Need move_in_date, useful move-in timing, or a clear flexible/browsing signal.

For student/sublet searches:
- Need a larger city or metro area.
- Budget per person or total budget is very useful, but if the user does not know it, treat budget as flexible and ask about room type or timing instead.
- Room type or bedroom need is very useful, but can be handled as unknown if the user is flexible.
- Move-in/move-out timing, semester/season timing, or lease/sublet duration is important. A phrase like summer program is a useful timing signal.

For affordable housing:
- Need location.
- Need at least one affordability signal such as section8, income_restricted, voucher, max_price, or notes indicating affordable housing.
- Ask for bedrooms or household size only if it appears material.

Output keys:
ready_to_search: boolean
ready_to_recommend: boolean
confidence: "low" | "medium" | "high"
next_action: "ask_followup" | "plan_search" | "request_confirmation" | "execute_search" | "rank_results"
missing_required_fields: array of strings
hard_constraints: array of strings
soft_preferences: array of strings
safe_assumptions: array of strings
followup_questions: array of strings
reasoning_summary: string

Do not include chain-of-thought. reasoning_summary should be brief and user-facing.
""".strip()


def build_readiness_messages(
    intent: HousingSearchIntent,
    *,
    transcript: Sequence[Mapping[str, str]] | None = None,
    today: str | None = None,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": READINESS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "today": today or date.today().isoformat(),
                    "intent": _intent_payload(intent),
                    "transcript": list(transcript or []),
                },
                ensure_ascii=False,
            ),
        },
    ]


def evaluate_search_readiness(
    intent: HousingSearchIntent,
    *,
    client: JsonChatClient | None = None,
    model: str | None = None,
    transcript: Sequence[Mapping[str, str]] | None = None,
    today: str | None = None,
) -> SearchReadiness:
    chat_client = client or MistralChatClient.from_env(model=model)
    messages = build_readiness_messages(intent, transcript=transcript, today=today)
    response_text = chat_client.complete_json(messages, temperature=0.0, max_tokens=1000)
    raw = parse_json_object(response_text)
    readiness = readiness_from_mapping(raw)
    return apply_readiness_guards(readiness, intent, transcript=transcript)


def readiness_from_mapping(data: Mapping[str, Any]) -> SearchReadiness:
    next_action = _choice(
        data.get("next_action"),
        {"ask_followup", "plan_search", "request_confirmation", "execute_search", "rank_results"},
        "ask_followup",
    )
    confidence = _choice(data.get("confidence"), {"low", "medium", "high"}, "low")
    return SearchReadiness(
        ready_to_search=_bool(data.get("ready_to_search")),
        ready_to_recommend=_bool(data.get("ready_to_recommend")),
        confidence=confidence,
        next_action=next_action,
        missing_required_fields=_string_tuple(data.get("missing_required_fields")),
        hard_constraints=_string_tuple(data.get("hard_constraints")),
        soft_preferences=_string_tuple(data.get("soft_preferences")),
        safe_assumptions=_string_tuple(data.get("safe_assumptions")),
        followup_questions=_string_tuple(data.get("followup_questions"))[:2],
        reasoning_summary=_optional_string(data.get("reasoning_summary")) or "",
    )


def apply_readiness_guards(
    readiness: SearchReadiness,
    intent: HousingSearchIntent,
    *,
    transcript: Sequence[Mapping[str, str]] | None = None,
) -> SearchReadiness:
    if not intent.location:
        return SearchReadiness(
            ready_to_search=False,
            ready_to_recommend=False,
            confidence=_lower_confidence(readiness.confidence),
            next_action="ask_followup",
            missing_required_fields=_merge_strings(("location",), readiness.missing_required_fields),
            hard_constraints=readiness.hard_constraints,
            soft_preferences=readiness.soft_preferences,
            safe_assumptions=readiness.safe_assumptions,
            followup_questions=("What larger city or metro area should I search in?",),
            reasoning_summary=(
                readiness.reasoning_summary
                or "I need a location before this search can be useful."
            ),
        )

    if is_neighborhood_only_location(intent.location):
        return SearchReadiness(
            ready_to_search=False,
            ready_to_recommend=False,
            confidence=_lower_confidence(readiness.confidence),
            next_action="ask_followup",
            missing_required_fields=_merge_strings(("larger city",), readiness.missing_required_fields),
            hard_constraints=readiness.hard_constraints,
            soft_preferences=readiness.soft_preferences,
            safe_assumptions=readiness.safe_assumptions,
            followup_questions=("What larger city or metro area should I search for that area?",),
            reasoning_summary="I need the larger city because the housing sites search city-wide, not by exact neighborhood.",
        )

    if not _has_provider_routing_signal(intent):
        return SearchReadiness(
            ready_to_search=False,
            ready_to_recommend=False,
            confidence=_lower_confidence(readiness.confidence),
            next_action="ask_followup",
            missing_required_fields=_merge_strings(("housing search type",), readiness.missing_required_fields),
            hard_constraints=readiness.hard_constraints,
            soft_preferences=readiness.soft_preferences,
            safe_assumptions=readiness.safe_assumptions,
            followup_questions=(
                "Is this just for you/private room/student/sublet, a regular rental/full rental with multiple roommates, or affordable/voucher/accessibility housing?",
            ),
            reasoning_summary="I need to choose the right housing source before searching.",
        )

    next_action = readiness.next_action
    if next_action in {"execute_search", "rank_results"}:
        next_action = "request_confirmation" if readiness.ready_to_search else "ask_followup"
    if readiness.followup_questions and next_action != "ask_followup":
        next_action = "ask_followup"
    if next_action == "ask_followup" and readiness.followup_questions:
        followup_questions = _drop_neighborhood_followups(
            _dedupe_repeated_followups(readiness.followup_questions, transcript=transcript)
        )
        if not followup_questions:
            return SearchReadiness(
                ready_to_search=True,
                ready_to_recommend=readiness.ready_to_recommend,
                confidence=readiness.confidence,
                next_action="request_confirmation",
                missing_required_fields=_drop_neighborhood_fields(readiness.missing_required_fields),
                hard_constraints=readiness.hard_constraints,
                soft_preferences=readiness.soft_preferences,
                safe_assumptions=_merge_strings(
                    ("Run the initial search city-wide; neighborhood preferences are not source filters.",),
                    readiness.safe_assumptions,
                ),
                followup_questions=(),
                reasoning_summary=(
                    readiness.reasoning_summary
                    or "I can start with a city-wide search because neighborhood preferences are not source filters."
                ),
            )
        return SearchReadiness(
            ready_to_search=False,
            ready_to_recommend=False,
            confidence=_lower_confidence(readiness.confidence),
            next_action="ask_followup",
            missing_required_fields=_drop_neighborhood_fields(readiness.missing_required_fields),
            hard_constraints=readiness.hard_constraints,
            soft_preferences=_drop_neighborhood_fields(readiness.soft_preferences),
            safe_assumptions=readiness.safe_assumptions,
            followup_questions=followup_questions,
            reasoning_summary=_clean_reasoning_summary(readiness.reasoning_summary, asking_followup=True),
        )

    if readiness.ready_to_search and not readiness.followup_questions:
        return SearchReadiness(
            ready_to_search=True,
            ready_to_recommend=readiness.ready_to_recommend,
            confidence=readiness.confidence,
            next_action="request_confirmation" if next_action == "plan_search" else next_action,
            missing_required_fields=(),
            hard_constraints=readiness.hard_constraints,
            soft_preferences=readiness.soft_preferences,
            safe_assumptions=readiness.safe_assumptions,
            followup_questions=(),
            reasoning_summary=readiness.reasoning_summary,
        )

    return SearchReadiness(
        ready_to_search=readiness.ready_to_search,
        ready_to_recommend=readiness.ready_to_recommend,
        confidence=readiness.confidence,
        next_action=next_action,
        missing_required_fields=readiness.missing_required_fields,
        hard_constraints=readiness.hard_constraints,
        soft_preferences=readiness.soft_preferences,
        safe_assumptions=readiness.safe_assumptions,
        followup_questions=_drop_neighborhood_followups(
            _dedupe_repeated_followups(readiness.followup_questions, transcript=transcript)
        ),
        reasoning_summary=_clean_reasoning_summary(readiness.reasoning_summary, asking_followup=next_action == "ask_followup"),
    )


def _intent_kind(intent: HousingSearchIntent) -> str:
    text = _intent_text(intent)
    if intent.section8 or intent.income_restricted or "voucher" in text or "section 8" in text or "section8" in text:
        return "affordable"
    if intent.intent_kind in {"affordable", "student_sublet", "general_rental", "apartment"}:
        return intent.intent_kind
    if intent.type_of_places or "sublet" in text or "student" in text or "campus" in text:
        return "student_sublet"
    return "general_rental"


def _has_provider_routing_signal(intent: HousingSearchIntent) -> bool:
    text = _intent_text(intent)
    if intent.intent_kind and intent.intent_kind != "unknown":
        return True
    if intent.roommate_count is not None:
        return True
    if intent.section8 or intent.income_restricted or intent.wheelchair_accessible:
        return True
    if intent.utilities_included or intent.washer_dryer:
        return True
    if intent.campus_or_school:
        return True
    if intent.type_of_places or intent.property_types:
        return True

    signals = (
        "student",
        "sublet",
        "sublease",
        "private room",
        "shared room",
        "just me",
        "only me",
        "for myself",
        "solo",
        "single person",
        "roommate",
        "roommates",
        "group rental",
        "apartment",
        "house",
        "townhouse",
        "condo",
        "voucher",
        "section 8",
        "section8",
        "affordable",
        "income restricted",
        "income-restricted",
        "accessible",
        "accessibility",
        "wheelchair",
    )
    return any(signal in text for signal in signals)


def _has_affordability_signal(intent: HousingSearchIntent) -> bool:
    text = _intent_text(intent)
    return bool(
        intent.section8
        or intent.income_restricted
        or intent.max_price is not None
        or "voucher" in text
        or "section 8" in text
        or "section8" in text
        or "income restricted" in text
        or "affordable" in text
    )


def _dedupe_repeated_followups(
    questions: Sequence[str],
    *,
    transcript: Sequence[Mapping[str, str]] | None,
) -> tuple[str, ...]:
    cleaned = _merge_strings(questions, ())
    if not transcript or len(transcript) < 2:
        return cleaned[:2]

    latest = str(transcript[-1].get("content", "")).lower()
    previous = str(transcript[-2].get("content", "")).lower()
    uncertainty_terms = ("don't know", "dont know", "not sure", "unsure", "no idea", "really know")
    user_is_uncertain = any(term in latest for term in uncertainty_terms)
    if not user_is_uncertain:
        return cleaned[:2]

    filtered: list[str] = []
    for question in cleaned:
        question_text = question.lower()
        if "budget" in question_text and ("budget" in previous or "maximum" in previous):
            continue
        filtered.append(question)
    if not filtered:
        filtered.append("Are you looking for a private room, shared room, or an entire place?")
    return tuple(filtered[:2])


def _drop_neighborhood_followups(questions: Sequence[str]) -> tuple[str, ...]:
    return tuple(question for question in questions if not asks_for_neighborhood_preference(question))


def _drop_neighborhood_fields(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(value for value in values if "neighborhood" not in value.lower() and "neighbourhood" not in value.lower())


def _clean_reasoning_summary(summary: str, *, asking_followup: bool) -> str:
    text = summary.strip()
    if asking_followup and "all required fields" in text.lower():
        return "One more detail would make this search more useful."
    return text


def _has_timing_signal(intent: HousingSearchIntent) -> bool:
    text = _intent_text(intent)
    timing_terms = (
        "asap",
        "flexible",
        "browse",
        "browsing",
        "summer",
        "fall",
        "spring",
        "semester",
        "month",
        "lease",
        "move",
    )
    return bool(intent.move_in_date or intent.move_out_date or intent.lease_length or any(term in text for term in timing_terms))


def _broad_search_requested(transcript: Sequence[Mapping[str, str]] | None) -> bool:
    if not transcript:
        return False
    latest = str(transcript[-1].get("content", "")).lower()
    cues = (
        "just browsing",
        "browsing generally",
        "show me options",
        "show options",
        "broad search",
        "search anyway",
        "i'm flexible",
        "im flexible",
        "flexible",
        "anything",
        "any place",
    )
    return any(cue in latest for cue in cues)


def _intent_text(intent: HousingSearchIntent) -> str:
    pieces = [
        intent.intent_kind or "",
        intent.keyword or "",
        intent.lease_length or "",
        intent.campus_or_school or "",
        intent.commute_target or "",
        *intent.notes,
        *intent.flexibility_notes,
        *intent.property_types,
        *intent.type_of_places,
        *intent.amenities,
        *intent.required_amenities,
        *intent.preferred_amenities,
    ]
    return " ".join(str(piece) for piece in pieces if piece).lower()


def _intent_payload(intent: HousingSearchIntent) -> dict[str, Any]:
    return {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in asdict(intent).items()
    }


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


def _lower_confidence(value: str) -> str:
    return "low" if value == "medium" else value if value == "low" else "medium"


def _choice(value: Any, allowed: set[str], default: str) -> str:
    text = _optional_string(value)
    if not text:
        return default
    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"true", "yes", "y", "1", "on"}


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "unknown", "n/a"}:
        return None
    return text


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


__all__ = [
    "READINESS_SYSTEM_PROMPT",
    "apply_readiness_guards",
    "build_readiness_messages",
    "evaluate_search_readiness",
    "readiness_from_mapping",
]
