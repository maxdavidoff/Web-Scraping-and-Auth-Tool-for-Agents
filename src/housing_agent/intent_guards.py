from __future__ import annotations

import re
from dataclasses import replace
from typing import Sequence

from .types import HousingSearchIntent


OPEN_BUDGET_NOTE = "budget_open"


def apply_intent_guards(
    intent: HousingSearchIntent,
    *,
    latest_user_message: str = "",
    transcript: Sequence[dict[str, str]] | None = None,
) -> HousingSearchIntent:
    text = _conversation_text(latest_user_message, transcript)
    guarded = _guard_budget(intent, latest_user_message or text)
    guarded = _guard_room_vs_unit(guarded, text)
    return guarded


def _guard_budget(intent: HousingSearchIntent, text: str) -> HousingSearchIntent:
    normalized = text.lower()
    if _budget_open(normalized):
        return replace(
            intent,
            min_price=None,
            max_price=None,
            flexibility_notes=_merge_strings(intent.flexibility_notes, (OPEN_BUDGET_NOTE,)),
        )

    parsed = _parse_budget(normalized)
    if parsed is not None:
        min_price, max_price = parsed
        return replace(intent, min_price=min_price, max_price=max_price)

    # The LLM often turns "3k/month" into an exact range. Unless the latest user
    # text clearly says exact/minimum/range, treat equal min/max as a max budget.
    if (
        intent.min_price is not None
        and intent.max_price is not None
        and intent.min_price == intent.max_price
        and not _mentions_exact_or_minimum(normalized)
    ):
        return replace(intent, min_price=None)

    return intent


def _guard_room_vs_unit(intent: HousingSearchIntent, text: str) -> HousingSearchIntent:
    if intent.bedrooms != 1:
        return intent

    normalized = text.lower()
    if _explicit_whole_unit_one_bed(normalized):
        return intent

    place_text = " ".join(intent.type_of_places).lower()
    notes_text = " ".join((*intent.notes, *intent.flexibility_notes)).lower()
    combined = " ".join((normalized, place_text, notes_text))
    if _room_or_larger_flat(combined):
        return replace(intent, bedrooms=None)
    return intent


def _parse_budget(text: str) -> tuple[int | None, int | None] | None:
    range_patterns = (
        r"\bbetween\s+(?P<lo>\$?\d+(?:\.\d+)?k?)\s+(?:and|-|to)\s+(?P<hi>\$?\d+(?:\.\d+)?k?)",
        r"\bfrom\s+(?P<lo>\$?\d+(?:\.\d+)?k?)\s+(?:to|-)\s+(?P<hi>\$?\d+(?:\.\d+)?k?)",
        r"(?P<lo>\$?\d+(?:\.\d+)?k?)\s*(?:-|to)\s*(?P<hi>\$?\d+(?:\.\d+)?k?)",
    )
    for pattern in range_patterns:
        match = re.search(pattern, text)
        if match:
            lo = _amount(match.group("lo"))
            hi = _amount(match.group("hi"))
            if lo is not None and hi is not None:
                if max(lo, hi) < 100:
                    continue
                return min(lo, hi), max(lo, hi)

    exact = re.search(r"\bexactly\s+(?P<amount>\$?\d+(?:\.\d+)?k?)", text)
    if exact:
        amount = _amount(exact.group("amount"))
        if amount is not None:
            return amount, amount

    minimum = re.search(r"\b(?:at\s+least|minimum|min(?:imum)?|from)\s+(?P<amount>\$?\d+(?:\.\d+)?k?)", text)
    if minimum:
        amount = _amount(minimum.group("amount"))
        if amount is not None:
            return amount, None

    maximum_patterns = (
        r"\b(?:up\s+to|under|below|less\s+than|maximum|max)\s+(?P<amount>\$?\d+(?:\.\d+)?k?)",
        r"\b(?:budget(?:\s+is)?|around|about|roughly|probably\s+like)\s+(?P<amount>\$?\d+(?:\.\d+)?k?)",
        r"(?P<amount>\$?\d+(?:\.\d+)?k?)\s*(?:/|\s+per\s+|\s+a\s+|\s+)?(?:month|mo|monthly)\b",
    )
    for pattern in maximum_patterns:
        match = re.search(pattern, text)
        if match:
            amount = _amount(match.group("amount"))
            if amount is not None:
                return None, amount

    currency = re.search(r"(?P<amount>\$\d+(?:,\d{3})*(?:\.\d+)?k?)", text)
    if currency:
        amount = _amount(currency.group("amount"))
        if amount is not None:
            return None, amount

    return None


def _amount(value: str) -> int | None:
    text = value.lower().replace("$", "").replace(",", "").strip()
    multiplier = 1000 if text.endswith("k") else 1
    if text.endswith("k"):
        text = text[:-1]
    try:
        return int(float(text) * multiplier)
    except ValueError:
        return None


def _budget_open(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "no budget",
            "don't know",
            "dont know",
            "not sure",
            "unsure",
            "flexible budget",
            "budget is flexible",
            "open budget",
        )
    )


def _mentions_exact_or_minimum(text: str) -> bool:
    return bool(re.search(r"\b(exactly|at\s+least|minimum|min(?:imum)?|from|between)\b", text))


def _explicit_whole_unit_one_bed(text: str) -> bool:
    return bool(
        re.search(r"\b(one|1)[-\s]?bed(?:room)?\s+(?:apartment|apt|flat|unit|place|home)\b", text)
        or re.search(r"\b(?:entire|whole)\s+(?:one|1)[-\s]?bed", text)
    )


def _room_or_larger_flat(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "private room",
            "shared room",
            "room for myself",
            "for myself",
            "larger flat",
            "more than one bedroom",
            "flat itself can",
            "sublet",
        )
    )


def _conversation_text(latest_user_message: str, transcript: Sequence[dict[str, str]] | None) -> str:
    parts = [latest_user_message]
    if transcript:
        parts.extend(str(item.get("content", "")) for item in transcript[-3:] if item.get("role") == "user")
    return " ".join(part for part in parts if part)


def _merge_strings(left: Sequence[str], right: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    values: list[str] = []
    for value in (*left, *right):
        text = str(value).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            values.append(text)
    return tuple(values)


__all__ = ["OPEN_BUDGET_NOTE", "apply_intent_guards"]
