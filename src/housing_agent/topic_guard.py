from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from .intent_extractor import JsonChatClient, parse_json_object
from .llm_client import DEFAULT_MISTRAL_MODEL, MistralChatClient
from .types import HousingSearchIntent


TOPIC_GUARD_SYSTEM_PROMPT = """
You are a housing-message topic guard for a rental-search chat agent.

Decide whether the latest user message belongs in a rental housing search conversation.
Return exactly one JSON object.

Treat a message as on-topic when it:
- asks for rental housing, sublets, rooms, apartments, affordable housing, vouchers, accessibility, roommates, lease timing, locations, budgets, amenities, or listing recommendations;
- answers a previous rental-housing follow-up, even tersely, such as "Boston", "under 1800", "June 1", "private room", "not sure", or "flexible";
- changes, corrects, confirms, or cancels part of the current rental search.

Treat a message as off-topic when it is primarily about something unrelated to rental housing, such as recipes, entertainment, homework, coding, general trivia, weather, jokes, or unrelated personal chat.

Do not choose providers, build URLs, mention scraping, output commands, or answer the user.

Output keys:
is_on_topic: boolean
confidence: "low" | "medium" | "high"
reasoning_summary: brief user-facing reason, without chain-of-thought
""".strip()


@dataclass(frozen=True)
class MessageTopicResult:
    is_on_topic: bool = True
    confidence: str = "low"
    reasoning_summary: str = ""


def build_topic_guard_messages(
    latest_user_message: str,
    *,
    current_intent: HousingSearchIntent | Mapping[str, Any] | None = None,
    transcript: Sequence[Mapping[str, str]] | None = None,
    today: str | None = None,
) -> list[dict[str, str]]:
    message = latest_user_message.strip()
    if not message:
        raise ValueError("Latest user message cannot be empty.")

    return [
        {"role": "system", "content": TOPIC_GUARD_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "today": today or date.today().isoformat(),
                    "latest_user_message": message,
                    "current_intent": _intent_payload(current_intent),
                    "transcript": list(transcript or [])[-6:],
                },
                ensure_ascii=False,
            ),
        },
    ]


def evaluate_message_topic(
    latest_user_message: str,
    *,
    client: JsonChatClient | None = None,
    model: str | None = None,
    current_intent: HousingSearchIntent | Mapping[str, Any] | None = None,
    transcript: Sequence[Mapping[str, str]] | None = None,
    today: str | None = None,
) -> MessageTopicResult:
    chat_client = client or MistralChatClient.from_env(model=model)
    messages = build_topic_guard_messages(
        latest_user_message,
        current_intent=current_intent,
        transcript=transcript,
        today=today,
    )
    response_text = chat_client.complete_json(messages, temperature=0.0, max_tokens=500)
    return topic_result_from_mapping(parse_json_object(response_text))


def topic_result_from_mapping(data: Mapping[str, Any]) -> MessageTopicResult:
    return MessageTopicResult(
        is_on_topic=_bool(data.get("is_on_topic"), default=True),
        confidence=_choice(data.get("confidence"), {"low", "medium", "high"}, "low"),
        reasoning_summary=_optional_string(data.get("reasoning_summary")) or "",
    )


def _intent_payload(value: HousingSearchIntent | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    payload = asdict(value) if isinstance(value, HousingSearchIntent) else dict(value)
    return {
        key: list(item) if isinstance(item, tuple) else item
        for key, item in payload.items()
    }


def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "on"}:
        return True
    if text in {"false", "no", "n", "0", "off"}:
        return False
    return default


def _choice(value: Any, allowed: set[str], default: str) -> str:
    text = _optional_string(value)
    if not text:
        return default
    normalized = text.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized if normalized in allowed else default


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "unknown", "n/a"}:
        return None
    return text


__all__ = [
    "MessageTopicResult",
    "TOPIC_GUARD_SYSTEM_PROMPT",
    "build_topic_guard_messages",
    "evaluate_message_topic",
    "topic_result_from_mapping",
]
