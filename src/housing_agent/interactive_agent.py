from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from src.ohana_agent.provider_router import run_provider_searches

from .intent_extractor import JsonChatClient, update_housing_intent
from .provider_capabilities import AFFORDABLEHOUSING, OHANA, RENTALSOURCE
from .search_app import (
    executable_provider_plan,
    legacy_router_plan_from_intent,
    query_plan_to_dict,
    user_visible_warnings,
)
from .types import HousingSearchIntent, QueryPlan


AgentRunner = Callable[..., Any]

HELP_TEXT = """
Commands:
  help, h                  Show this help.
  show                     Show the current intent and plan.
  plan                     Review the current provider plan.
  execute                  Prepare execution confirmation.
  yes                      Run only when execution confirmation is pending.
  no                       Cancel pending execution confirmation.
  json                     Show debug JSON for the current state.
  transcript               Show this session's user transcript.
  max-listings <n>, max <n> Set max listings per provider.
  reset, clear             Clear this search and start over.
  quit, exit, q            Leave the chat.
""".strip()


@dataclass(frozen=True)
class AgentTurn:
    state: str
    message: str
    intent: HousingSearchIntent | None = None
    query_plan: QueryPlan | None = None
    execution_result: Any | None = None
    json_payload: Mapping[str, Any] | None = None


class InteractiveHousingAgent:
    def __init__(
        self,
        *,
        client: JsonChatClient | None = None,
        model: str | None = None,
        providers: Sequence[str] | None = None,
        runner: AgentRunner = run_provider_searches,
        today: str | None = None,
        max_listings: int = 10,
        scrolls: int = 3,
        headless: bool = True,
        state_file: str | None = None,
        selectors_file: str | None = None,
        fetch_listing_api: bool = False,
        capture_detail_urls: bool = False,
    ) -> None:
        self.client = client
        self.model = model
        self.providers = tuple(providers) if providers else None
        self.runner = runner
        self.today = today
        self.max_listings = max_listings
        self.scrolls = scrolls
        self.headless = headless
        self.state_file = state_file
        self.selectors_file = selectors_file
        self.fetch_listing_api = fetch_listing_api
        self.capture_detail_urls = capture_detail_urls

        self.transcript: list[dict[str, str]] = []
        self.current_intent: HousingSearchIntent | None = None
        self.latest_plan: QueryPlan | None = None
        self.latest_planning_payload: dict[str, Any] | None = None
        self.latest_execution_result: Any | None = None
        self.pending_execution_confirmation = False

    def handle_user_message(self, raw_message: str) -> AgentTurn:
        message = raw_message.strip()
        if not message:
            return AgentTurn(
                state="collecting",
                message="Tell me what kind of housing you are looking for.",
                intent=self.current_intent,
                query_plan=self.latest_plan,
            )

        command_turn = self._handle_command(message)
        if command_turn is not None:
            return command_turn

        self.pending_execution_confirmation = False
        self.latest_execution_result = None
        previous_transcript = list(self.transcript)
        self.transcript.append({"role": "user", "content": message})

        try:
            extraction = update_housing_intent(
                self.current_intent,
                message,
                client=self.client,
                model=self.model,
                transcript=previous_transcript,
                providers=self.providers,
                today=self.today,
            )
        except Exception as exc:
            return AgentTurn(
                state="error",
                message=f"I could not update the housing intent: {exc}",
                intent=self.current_intent,
                query_plan=self.latest_plan,
            )

        self.current_intent = extraction.intent
        self.latest_plan = extraction.query_plan
        self.latest_planning_payload = self._planning_payload()

        clarification = self._clarification_question(self.current_intent)
        if clarification:
            return AgentTurn(
                state="needs_clarification",
                message=clarification,
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )

        return AgentTurn(
            state="planned",
            message=self.render_plan(),
            intent=self.current_intent,
            query_plan=self.latest_plan,
            json_payload=self.current_state_payload(),
        )

    def reset(self) -> AgentTurn:
        self.transcript = []
        self.current_intent = None
        self.latest_plan = None
        self.latest_planning_payload = None
        self.latest_execution_result = None
        self.pending_execution_confirmation = False
        return AgentTurn(
            state="reset",
            message="Reset complete. Tell me what kind of housing you are looking for.",
            json_payload=self.current_state_payload(),
        )

    def current_state_payload(self) -> dict[str, Any]:
        return {
            "state": self._current_state(),
            "intent": _to_jsonable(self.current_intent),
            "query_plan": query_plan_to_dict(self.latest_plan) if self.latest_plan else None,
            "pending_execution_confirmation": self.pending_execution_confirmation,
            "max_listings": self.max_listings,
            "execution_result": self._execution_payload(self.latest_execution_result),
            "transcript": list(self.transcript),
        }

    def render_plan(self) -> str:
        if not self.current_intent or not self.latest_plan:
            return "No plan is available yet. Tell me what you are looking for first."

        lines = [
            "Current housing search plan",
            "",
            "Intent:",
        ]
        lines.extend(f"- {line}" for line in _intent_summary_lines(self.current_intent))
        lines.extend(["", "Provider ranking:"])

        for index, provider_plan in enumerate(self.latest_plan.provider_plans, start=1):
            lines.append(
                f"{index}. {provider_plan.provider} — {provider_plan.quality} "
                f"(score {provider_plan.score:g}); {_why_line(provider_plan.reasons)}"
            )
            source = ", ".join(provider_plan.report.applied_at_source) or "none"
            post = ", ".join(provider_plan.report.post_filters) or "none"
            unsupported = ", ".join(provider_plan.report.unsupported) or "none"
            unknown = ", ".join(provider_plan.report.unknown_unverified) or "none"
            lines.append(f"   Source-applied: {source}")
            lines.append(f"   Post-filtered: {post}")
            lines.append(f"   Unsupported: {unsupported}")
            lines.append(f"   Unknown/unverified: {unknown}")

        warnings = user_visible_warnings(
            self.latest_plan,
            execute=False,
            skipped_providers=executable_provider_plan(self.latest_plan)[1],
        )
        if warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {warning}" for warning in warnings)

        lines.extend(["", "No search has run yet. Type `execute` to review what would run."])
        return "\n".join(lines)

    def render_execution_confirmation(self) -> str:
        if not self.latest_plan:
            return "No plan is available yet."

        executable_providers, skipped = executable_provider_plan(self.latest_plan)
        provider_text = ", ".join(executable_providers) or "none"
        browser_mode = "headless" if self.headless else "headed"
        lines = [
            "I am ready to run the deterministic provider router.",
            f"- Providers: {provider_text}",
            f"- Max listings per provider: {self.max_listings}",
            f"- Browser mode: {browser_mode}",
        ]
        if self.state_file:
            lines.append(f"- Browser state file: {self.state_file}")
        if OHANA in executable_providers:
            lines.append("- Caveat: Ohana may require a saved login session. If it fails, run save_ohana_login.py first.")
        for skipped_provider in skipped:
            lines.append(f"- Skipped: {skipped_provider['provider']} ({skipped_provider['reason']})")
        lines.append("")
        lines.append("Type `yes` to run or `no` to cancel.")
        return "\n".join(lines)

    def render_execution_result(self, result: Any) -> str:
        provider_results = list(getattr(result, "provider_results", []) or [])
        records = list(getattr(result, "records", []) or [])
        errors = dict(getattr(result, "errors", {}) or {})

        lines = [
            "Search execution finished.",
            f"- Listings returned: {len(records)}",
        ]
        if provider_results:
            lines.append("")
            lines.append("Provider statuses:")
            for provider_result in provider_results:
                provider = getattr(provider_result, "provider", "")
                status = getattr(provider_result, "status", "")
                count = len(getattr(provider_result, "records", []) or [])
                error = getattr(provider_result, "error", "")
                suffix = f" — {error}" if error else ""
                lines.append(f"- {provider}: {status}, {count} listing(s){suffix}")

        if records:
            lines.append("")
            lines.append("Top listings:")
            for record in records[:5]:
                title = record.get("title") or record.get("name") or "Untitled listing"
                price = record.get("price") or record.get("rent") or ""
                location = record.get("address") or record.get("location") or ""
                provider = record.get("provider") or record.get("source") or ""
                pieces = [piece for piece in [title, price, location, provider] if piece]
                lines.append(f"- {' | '.join(str(piece) for piece in pieces)}")

        artifacts = _artifact_lines(provider_results)
        if artifacts:
            lines.append("")
            lines.append("Artifacts:")
            lines.extend(f"- {artifact}" for artifact in artifacts)

        if errors:
            lines.append("")
            lines.append("Errors:")
            lines.extend(f"- {provider}: {error}" for provider, error in errors.items())

        return "\n".join(lines)

    def _handle_command(self, message: str) -> AgentTurn | None:
        lower = message.lower().strip()
        if lower in {"help", "h"}:
            return AgentTurn(state="collecting", message=HELP_TEXT, json_payload=self.current_state_payload())
        if lower in {"quit", "exit", "q"}:
            return AgentTurn(state="quit", message="Goodbye.")
        if lower in {"reset", "clear"}:
            return self.reset()
        if lower == "show":
            return AgentTurn(
                state=self._current_state(),
                message=self.render_plan() if self.latest_plan else "No plan is available yet.",
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        if lower == "plan":
            return self._plan_command()
        if lower == "execute":
            return self._execute_command()
        if lower == "yes":
            return self._yes_command()
        if lower == "no":
            return self._no_command()
        if lower == "json":
            payload = self.current_state_payload()
            return AgentTurn(
                state=self._current_state(),
                message=json.dumps(payload, indent=2, ensure_ascii=False),
                intent=self.current_intent,
                query_plan=self.latest_plan,
                execution_result=self.latest_execution_result,
                json_payload=payload,
            )
        if lower == "transcript":
            return AgentTurn(
                state=self._current_state(),
                message=_render_transcript(self.transcript),
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        max_listings = _parse_max_listings_command(lower)
        if max_listings is not None:
            if max_listings <= 0:
                return AgentTurn(
                    state="blocked",
                    message="Max listings must be a positive integer.",
                    intent=self.current_intent,
                    query_plan=self.latest_plan,
                    json_payload=self.current_state_payload(),
                )
            self.max_listings = max_listings
            self.pending_execution_confirmation = False
            return AgentTurn(
                state=self._current_state(),
                message=f"Max listings per provider set to {self.max_listings}.",
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        return None

    def _plan_command(self) -> AgentTurn:
        if not self.current_intent:
            return AgentTurn(
                state="blocked",
                message="No search intent is available yet. Tell me what you are looking for first.",
                json_payload=self.current_state_payload(),
            )
        clarification = self._clarification_question(self.current_intent)
        if clarification:
            return AgentTurn(
                state="needs_clarification",
                message=clarification,
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        if not self.latest_plan:
            return AgentTurn(
                state="blocked",
                message="No provider plan is available yet. Tell me what you are looking for first.",
                intent=self.current_intent,
                json_payload=self.current_state_payload(),
            )
        return AgentTurn(
            state="planned",
            message=self.render_plan(),
            intent=self.current_intent,
            query_plan=self.latest_plan,
            json_payload=self.current_state_payload(),
        )

    def _execute_command(self) -> AgentTurn:
        if not self.current_intent or not self.latest_plan:
            return AgentTurn(
                state="blocked",
                message="Execution is blocked until there is a provider plan. Tell me what you are looking for first.",
                json_payload=self.current_state_payload(),
            )
        clarification = self._clarification_question(self.current_intent)
        if clarification:
            return AgentTurn(
                state="needs_clarification",
                message=clarification,
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        executable_providers, _skipped = executable_provider_plan(self.latest_plan)
        if not executable_providers:
            return AgentTurn(
                state="blocked",
                message="Execution is blocked because no executable provider is available for this plan.",
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        self.pending_execution_confirmation = True
        return AgentTurn(
            state="execution_confirmation_requested",
            message=self.render_execution_confirmation(),
            intent=self.current_intent,
            query_plan=self.latest_plan,
            json_payload=self.current_state_payload(),
        )

    def _yes_command(self) -> AgentTurn:
        if not self.pending_execution_confirmation:
            return AgentTurn(
                state="blocked",
                message="There is no search awaiting confirmation yet. Tell me what you are looking for, or type `plan` if you want to review the current search.",
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        if not self.current_intent or not self.latest_plan:
            self.pending_execution_confirmation = False
            return AgentTurn(
                state="blocked",
                message="Execution is blocked because the current plan is missing.",
                json_payload=self.current_state_payload(),
            )

        executable_providers, _skipped = executable_provider_plan(self.latest_plan)
        execution_plan = legacy_router_plan_from_intent(
            self.current_intent,
            providers=executable_providers,
            max_listings=self.max_listings,
        )
        try:
            result = self.runner(
                execution_plan,
                providers=executable_providers,
                max_listings=self.max_listings,
                scrolls=self.scrolls,
                headless=self.headless,
                state_file=self.state_file,
                selectors_file=self.selectors_file,
                fetch_listing_api=self.fetch_listing_api,
                capture_detail_urls=self.capture_detail_urls,
            )
        except Exception as exc:
            self.pending_execution_confirmation = False
            return AgentTurn(
                state="error",
                message=f"Search execution failed before provider results were returned: {exc}",
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )

        self.pending_execution_confirmation = False
        self.latest_execution_result = result
        return AgentTurn(
            state="executed",
            message=self.render_execution_result(result),
            intent=self.current_intent,
            query_plan=self.latest_plan,
            execution_result=result,
            json_payload=self.current_state_payload(),
        )

    def _no_command(self) -> AgentTurn:
        if not self.pending_execution_confirmation:
            return AgentTurn(
                state="blocked",
                message="Nothing is awaiting confirmation.",
                intent=self.current_intent,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        self.pending_execution_confirmation = False
        return AgentTurn(
            state="planned",
            message="Execution canceled. No search has run.",
            intent=self.current_intent,
            query_plan=self.latest_plan,
            json_payload=self.current_state_payload(),
        )

    def _clarification_question(self, intent: HousingSearchIntent) -> str | None:
        if not intent.location:
            return "What city, neighborhood, campus area, or ZIP code should I search in?"
        if not _has_purpose_signal(intent):
            return "Is this a student/sublet room search, a regular rental search, or affordable/voucher housing?"
        return None

    def _planning_payload(self) -> dict[str, Any] | None:
        if not self.current_intent or not self.latest_plan:
            return None
        executable_providers, skipped = executable_provider_plan(self.latest_plan)
        return {
            "intent": _to_jsonable(self.current_intent),
            "query_plan": query_plan_to_dict(self.latest_plan),
            "execution": {
                "requested": False,
                "executed_providers": [],
                "executable_providers": list(executable_providers),
                "skipped_providers": skipped,
                "max_listings": self.max_listings,
            },
            "provider_results": [],
            "records": [],
            "errors": {},
            "warnings": user_visible_warnings(self.latest_plan, execute=False, skipped_providers=skipped),
        }

    def _execution_payload(self, result: Any | None) -> dict[str, Any] | None:
        if result is None:
            return None
        return {
            "provider_results": [
                {
                    "provider": getattr(provider_result, "provider", ""),
                    "status": getattr(provider_result, "status", ""),
                    "error": getattr(provider_result, "error", ""),
                    "search_url": getattr(provider_result, "search_url", ""),
                    "records_count": len(getattr(provider_result, "records", []) or []),
                    "raw_output": _to_jsonable(getattr(provider_result, "raw_output", None)),
                    "csv_output": _to_jsonable(getattr(provider_result, "csv_output", None)),
                    "debug_artifacts": _to_jsonable(getattr(provider_result, "debug_artifacts", None)),
                }
                for provider_result in list(getattr(result, "provider_results", []) or [])
            ],
            "records": _to_jsonable(list(getattr(result, "records", []) or [])),
            "errors": dict(getattr(result, "errors", {}) or {}),
        }

    def _current_state(self) -> str:
        if self.pending_execution_confirmation:
            return "execution_confirmation_requested"
        if self.latest_execution_result is not None:
            return "executed"
        if self.latest_plan is not None:
            clarification = self._clarification_question(self.current_intent) if self.current_intent else None
            return "needs_clarification" if clarification else "planned"
        if self.current_intent is not None:
            return "collecting"
        return "collecting"


def _has_purpose_signal(intent: HousingSearchIntent) -> bool:
    if intent.intent_kind and intent.intent_kind != "unknown":
        return True
    if intent.section8 or intent.income_restricted or intent.wheelchair_accessible:
        return True
    if intent.utilities_included or intent.washer_dryer:
        return True
    if intent.type_of_places:
        return True
    if intent.property_types:
        return True

    text = " ".join([*intent.notes, intent.keyword or ""]).lower()
    purpose_terms = (
        "student",
        "sublet",
        "sublease",
        "room",
        "roommate",
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
        "regular rental",
        "general rental",
        "normal apartment",
    )
    return any(term in text for term in purpose_terms)


def _intent_summary_lines(intent: HousingSearchIntent) -> list[str]:
    data = _to_jsonable(intent)
    labels = {
        "location": "Location",
        "min_price": "Min price",
        "max_price": "Max price",
        "bedrooms": "Bedrooms",
        "bedroom_min": "Bedroom min",
        "bedroom_max": "Bedroom max",
        "bathrooms": "Bathrooms",
        "bathroom_min": "Bathroom min",
        "property_types": "Property types",
        "type_of_places": "Place type",
        "pet_policy": "Pet policy",
        "furnished": "Furnished",
        "move_in_date": "Move in",
        "move_out_date": "Move out",
        "amenities": "Amenities",
        "sort": "Sort",
        "section8": "Section 8",
        "income_restricted": "Income restricted",
        "wheelchair_accessible": "Wheelchair accessible",
        "utilities_included": "Utilities included",
        "washer_dryer": "Washer/dryer",
        "keyword": "Keyword",
        "intent_kind": "Intent kind",
        "notes": "Notes",
    }
    lines: list[str] = []
    for key, label in labels.items():
        value = data.get(key)
        if value is None or value == "" or value == [] or value is False:
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value)
        else:
            rendered = str(value)
        lines.append(f"{label}: {rendered}")
    return lines or ["No concrete filters yet"]


def _why_line(reasons: Sequence[str]) -> str:
    profile_reasons = [reason for reason in reasons if "fit" in reason]
    if profile_reasons:
        return profile_reasons[0]
    useful_reasons = [reason for reason in reasons if "verified source" in reason or "unsupported" in reason]
    if useful_reasons:
        return "; ".join(useful_reasons[:2])
    return reasons[0] if reasons else "ranked by provider capability fit"


def _artifact_lines(provider_results: Sequence[Any]) -> list[str]:
    lines: list[str] = []
    for provider_result in provider_results:
        provider = getattr(provider_result, "provider", "")
        raw_output = getattr(provider_result, "raw_output", None)
        csv_output = getattr(provider_result, "csv_output", None)
        if raw_output:
            lines.append(f"{provider} raw: {raw_output}")
        if csv_output:
            lines.append(f"{provider} csv: {csv_output}")
        for name, path in (getattr(provider_result, "debug_artifacts", None) or {}).items():
            lines.append(f"{provider} {name}: {path}")
    return lines


def _render_transcript(transcript: Sequence[Mapping[str, str]]) -> str:
    if not transcript:
        return "Transcript is empty."
    return "\n".join(f"{item.get('role', 'user')}: {item.get('content', '')}" for item in transcript)


def _parse_max_listings_command(command: str) -> int | None:
    parts = command.split()
    if len(parts) != 2 or parts[0] not in {"max", "max-listings"}:
        return None
    try:
        return int(parts[1])
    except ValueError:
        return 0


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
