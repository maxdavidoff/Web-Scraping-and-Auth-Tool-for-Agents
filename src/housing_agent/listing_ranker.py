from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from .intent_extractor import JsonChatClient, parse_json_object
from .llm_client import MistralChatClient
from .types import HousingSearchIntent, ListingRankingResult, RankedListing, SearchReadiness


LISTING_RANKER_SYSTEM_PROMPT = """
You are a cautious housing listing ranker.

You receive:
1. A user's HousingSearchIntent.
2. A SearchReadiness object.
3. Listing records returned by deterministic provider tools.

Your job is to rank listings by fit.

Do not invent facts. Use only fields present in the listing records.
If a listing is missing an important field, mark it as unknown rather than assuming.
Distinguish hard-constraint failures from soft-preference weaknesses.
A listing that violates a hard constraint should not be recommended, but may be shown under "excluded" with the reason.
A listing with unknown information may be shown as "needs_verification".

Price interpretation:
- intent.max_price and intent.min_price are MONTHLY rent budgets unless intent.price_basis explicitly says otherwise.
- Listing prices like "$1,650/mo", "$1,650/month", or a bare "$1,650" on a rental card are also monthly rent.
- Do NOT multiply a monthly listing price by the number of months in a sublet, summer program, or lease term to compare against the user's budget. "For the summer" is a timing signal, not a budget multiplier.
- A monthly listing price that is at or below intent.max_price satisfies the price constraint, regardless of how long the user plans to stay.
- The ONLY price-based reason to exclude a listing is: parsed monthly listing price > intent.max_price, OR parsed monthly listing price < intent.min_price. Nothing else.
- intent.price_basis ("total" / "per_person" / "per_room") describes who the budget covers, NOT the price period. Do not exclude a listing for "price basis mismatch": when type_of_places includes "Private room", a listing showing "$X/mo" for that room IS the per-room price. There is no mismatch to act on.
- If you cannot parse a monthly number from the listing price, mark price as missing_info and bucket the listing as needs_verification — do not exclude.

Return exactly one JSON object.

Output keys:
recommended: array
needs_verification: array
excluded: array
overall_summary: string
followup_suggestions: array

Each listing object should include:
listing_id
title
url
fit_score: number from 0 to 100
matched_constraints: array of strings
missing_info: array of strings
concerns: array of strings
why_it_fits: string
provider
""".strip()


def build_listing_ranker_messages(
    intent: HousingSearchIntent,
    readiness: SearchReadiness | None,
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": LISTING_RANKER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "intent": _to_jsonable(intent),
                    "search_readiness": _to_jsonable(readiness),
                    "records": _to_jsonable(list(records)),
                },
                ensure_ascii=False,
            ),
        },
    ]


def rank_listings(
    intent: HousingSearchIntent,
    readiness: SearchReadiness | None,
    records: Sequence[Mapping[str, Any]],
    *,
    client: JsonChatClient | None = None,
    model: str | None = None,
) -> ListingRankingResult:
    if not records:
        return ListingRankingResult(overall_summary="No listings were returned to rank.")

    chat_client = client or MistralChatClient.from_env(model=model)
    messages = build_listing_ranker_messages(intent, readiness, records)
    response_text = chat_client.complete_json(messages, temperature=0.0, max_tokens=1600)
    raw = parse_json_object(response_text)
    return ranking_from_mapping(raw)


def ranking_from_mapping(data: Mapping[str, Any]) -> ListingRankingResult:
    return ListingRankingResult(
        recommended=_listing_tuple(data.get("recommended")),
        needs_verification=_listing_tuple(data.get("needs_verification")),
        excluded=_listing_tuple(data.get("excluded")),
        overall_summary=_optional_string(data.get("overall_summary")) or "",
        followup_suggestions=_string_tuple(data.get("followup_suggestions")),
        raw_response=dict(data),
    )


def _listing_tuple(value: Any) -> tuple[RankedListing, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, Mapping):
        values = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = list(value)
    else:
        values = []
    return tuple(_ranked_listing_from_mapping(item) for item in values if isinstance(item, Mapping))


def _ranked_listing_from_mapping(data: Mapping[str, Any]) -> RankedListing:
    return RankedListing(
        listing_id=_optional_string(data.get("listing_id") or data.get("id")) or "",
        title=_optional_string(data.get("title") or data.get("name")) or "",
        url=_optional_string(data.get("url") or data.get("listing_url") or data.get("detail_url")) or "",
        fit_score=_score(data.get("fit_score")),
        matched_constraints=_string_tuple(data.get("matched_constraints")),
        missing_info=_string_tuple(data.get("missing_info")),
        concerns=_string_tuple(data.get("concerns")),
        why_it_fits=_optional_string(data.get("why_it_fits")) or "",
        provider=_optional_string(data.get("provider") or data.get("source")) or "",
        raw=dict(data),
    )


def _score(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


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


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_to_jsonable(item) for item in value]
    if hasattr(value, "__fspath__"):
        return value.__fspath__()
    return value


__all__ = [
    "LISTING_RANKER_SYSTEM_PROMPT",
    "build_listing_ranker_messages",
    "rank_listings",
    "ranking_from_mapping",
]
