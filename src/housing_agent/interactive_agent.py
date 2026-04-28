from __future__ import annotations

import json
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Callable, Mapping, Sequence

from src.ohana_agent.provider_router import run_provider_searches

from .intent_extractor import JsonChatClient, update_housing_intent
from .listing_ranker import rank_listings
from .post_filter import apply_hard_constraints
from .provider_capabilities import AFFORDABLEHOUSING, OHANA, RENTALSOURCE
from .readiness_evaluator import evaluate_search_readiness
from .search_app import (
    executable_provider_plan,
    legacy_router_plan_from_intent,
    query_plan_to_dict,
    user_visible_warnings,
)
from .types import HousingSearchIntent, ListingRankingResult, QueryPlan, RankedListing, SearchReadiness


AgentRunner = Callable[..., Any]
ReadinessEvaluator = Callable[..., SearchReadiness]
ListingRanker = Callable[..., ListingRankingResult]

HELP_TEXT = """
Tell me what you are looking for in normal language. I will ask one clarification if I need it, then suggest the best source to search first.

Useful replies:
  yes                      Run the proposed search.
  no                       Do not run the proposed search.
  reset, clear             Start over.
  quit, exit, q            Leave the chat.

Debug commands:
  show, plan               Review the current plan.
  json                     Show debug JSON for the current state.
  transcript               Show this session's user transcript.
  max-listings <n>, max <n> Set max listings per provider.
""".strip()


@dataclass(frozen=True)
class AgentTurn:
    state: str
    message: str
    intent: HousingSearchIntent | None = None
    search_readiness: SearchReadiness | None = None
    query_plan: QueryPlan | None = None
    execution_result: Any | None = None
    listing_ranking: ListingRankingResult | None = None
    json_payload: Mapping[str, Any] | None = None


class InteractiveHousingAgent:
    def __init__(
        self,
        *,
        client: JsonChatClient | None = None,
        model: str | None = None,
        providers: Sequence[str] | None = None,
        runner: AgentRunner = run_provider_searches,
        readiness_evaluator: ReadinessEvaluator = evaluate_search_readiness,
        listing_ranker: ListingRanker = rank_listings,
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
        self.readiness_evaluator = readiness_evaluator
        self.listing_ranker = listing_ranker
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
        self.latest_readiness: SearchReadiness | None = None
        self.latest_plan: QueryPlan | None = None
        self.latest_planning_payload: dict[str, Any] | None = None
        self.latest_execution_result: Any | None = None
        self.latest_listing_ranking: ListingRankingResult | None = None
        self.latest_ranking_error: str = ""
        self.latest_hard_excluded_records: list[dict[str, Any]] = []
        self.latest_hard_exclusion_counts: dict[str, int] = {}
        self.pending_execution_confirmation = False
        self.proposed_execution_providers: tuple[str, ...] = ()

    def handle_user_message(self, raw_message: str) -> AgentTurn:
        message = raw_message.strip()
        if not message:
            return AgentTurn(
                state="collecting",
                message="Tell me what kind of housing you are looking for.",
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
            )

        command_turn = self._handle_command(message)
        if command_turn is not None:
            return command_turn

        self.pending_execution_confirmation = False
        self.proposed_execution_providers = ()
        self.latest_execution_result = None
        self.latest_listing_ranking = None
        self.latest_ranking_error = ""
        self.latest_hard_excluded_records = []
        self.latest_hard_exclusion_counts = {}
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
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
            )

        self.current_intent = extraction.intent
        self.latest_plan = extraction.query_plan

        try:
            self.latest_readiness = self.readiness_evaluator(
                self.current_intent,
                client=self.client,
                model=self.model,
                transcript=self.transcript,
                today=self.today,
            )
        except Exception as exc:
            return AgentTurn(
                state="error",
                message=f"I could not evaluate search readiness: {exc}",
                intent=self.current_intent,
                query_plan=self.latest_plan,
            )

        self.latest_planning_payload = self._planning_payload()

        clarification = self._readiness_followup()
        if clarification:
            return AgentTurn(
                state="needs_clarification",
                message=clarification,
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )

        return self._agent_led_planning_turn()

    def reset(self) -> AgentTurn:
        self.transcript = []
        self.current_intent = None
        self.latest_readiness = None
        self.latest_plan = None
        self.latest_planning_payload = None
        self.latest_execution_result = None
        self.latest_listing_ranking = None
        self.latest_ranking_error = ""
        self.latest_hard_excluded_records = []
        self.latest_hard_exclusion_counts = {}
        self.pending_execution_confirmation = False
        self.proposed_execution_providers = ()
        return AgentTurn(
            state="reset",
            message="Reset complete. Tell me what kind of housing you are looking for.",
            json_payload=self.current_state_payload(),
        )

    def current_state_payload(self) -> dict[str, Any]:
        return {
            "state": self._current_state(),
            "intent": _to_jsonable(self.current_intent),
            "search_readiness": _to_jsonable(self.latest_readiness),
            "query_plan": query_plan_to_dict(self.latest_plan) if self.latest_plan else None,
            "pending_execution_confirmation": self.pending_execution_confirmation,
            "proposed_execution_providers": list(self.proposed_execution_providers),
            "max_listings": self.max_listings,
            "execution_result": self._execution_payload(self.latest_execution_result),
            "listing_ranking": _to_jsonable(self.latest_listing_ranking),
            "ranking_error": self.latest_ranking_error,
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
        if self.latest_readiness:
            lines.extend(["", "Readiness:"])
            lines.extend(f"- {line}" for line in _readiness_summary_lines(self.latest_readiness))
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

        recommended = self._recommended_execution_providers()
        if recommended:
            lines.extend(
                [
                    "",
                    _proposal_sentence(recommended, self.max_listings),
                ]
            )
        else:
            lines.extend(["", "No search has run yet."])
        return "\n".join(lines)

    def render_execution_confirmation(self) -> str:
        if not self.latest_plan:
            return "No plan is available yet."

        providers = self.proposed_execution_providers or self._recommended_execution_providers()
        executable_providers, skipped = executable_provider_plan(self.latest_plan)
        provider_text = ", ".join(_provider_label(provider) for provider in providers) or "none"
        browser_mode = "headless" if self.headless else "headed"
        lines = [
            "I can run this search now.",
            f"- Providers: {provider_text}",
            f"- Max listings per provider: {self.max_listings}",
            f"- Browser mode: {browser_mode}",
        ]
        if self.state_file:
            lines.append(f"- Browser state file: {self.state_file}")
        if OHANA in providers:
            lines.append("- Caveat: Ohana may require a saved login session. If it fails, run save_ohana_login.py first.")
        for skipped_provider in skipped:
            lines.append(f"- Skipped: {skipped_provider['provider']} ({skipped_provider['reason']})")
        lines.append("")
        lines.append("Want me to run it?")
        return "\n".join(lines)

    def render_execution_result(self, result: Any) -> str:
        provider_results = list(getattr(result, "provider_results", []) or [])
        records = list(getattr(result, "records", []) or [])
        errors = dict(getattr(result, "errors", {}) or {})
        excluded_count = len(getattr(result, "excluded_records", []) or []) + len(self.latest_hard_excluded_records)

        lines = [
            "Search execution finished.",
            f"- Listings returned: {len(records)}",
        ]
        if excluded_count:
            lines.append(f"- Listings hidden by filters: {excluded_count}")
        if self.latest_readiness and not self.latest_readiness.ready_to_recommend:
            lines.append("- Recommendation confidence: limited; some important details were missing or assumptions were made.")
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

        if self.latest_listing_ranking:
            ranking = self.latest_listing_ranking
            if ranking.overall_summary:
                lines.extend(["", ranking.overall_summary])
            if ranking.recommended:
                lines.extend(["", "Recommended:"])
                for listing in ranking.recommended[:5]:
                    lines.append(f"- {_ranked_listing_line(listing)}")
            if ranking.needs_verification:
                lines.extend(["", "Needs verification:"])
                for listing in ranking.needs_verification[:5]:
                    lines.append(f"- {_ranked_listing_line(listing)}")
            if ranking.excluded:
                lines.extend(["", "Excluded:"])
                for listing in ranking.excluded[:5]:
                    lines.append(f"- {_ranked_listing_line(listing)}")
            if ranking.followup_suggestions:
                lines.extend(["", "Useful next checks:"])
                lines.extend(f"- {suggestion}" for suggestion in ranking.followup_suggestions[:3])
        elif records:
            lines.append("")
            lines.append("Top listings:")
            for record in records[:5]:
                title = record.get("title") or record.get("name") or "Untitled listing"
                price = record.get("price") or record.get("rent") or ""
                location = record.get("address") or record.get("location") or ""
                provider = record.get("provider") or record.get("source") or ""
                pieces = [piece for piece in [title, price, location, provider] if piece]
                lines.append(f"- {' | '.join(str(piece) for piece in pieces)}")
        if self.latest_ranking_error:
            lines.extend(["", f"Ranking note: listing fit ranking failed, so these are unranked results ({self.latest_ranking_error})."])

        artifacts = _artifact_lines(provider_results)
        if artifacts:
            lines.append("")
            lines.append("Artifacts:")
            lines.extend(f"- {artifact}" for artifact in artifacts)

        if errors:
            lines.append("")
            lines.append("Errors:")
            lines.extend(f"- {provider}: {error}" for provider, error in errors.items())

        if not records or (self.latest_hard_excluded_records and len(self.latest_hard_excluded_records) >= len(records)):
            suggestion = _broaden_retry_suggestion(
                self.latest_hard_exclusion_counts or getattr(result, "exclusion_counts", {}) or {},
                self.current_intent,
            )
            if suggestion:
                lines.extend(["", suggestion])

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
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        if lower == "plan":
            return self._plan_command()
        if lower == "execute":
            return self._execute_command()
        if lower in {"yes", "y", "go ahead", "search", "run it", "please do", "do it"}:
            return self._yes_command()
        if lower in {"no", "n", "cancel", "not now"}:
            return self._no_command()
        if lower == "json":
            payload = self.current_state_payload()
            return AgentTurn(
                state=self._current_state(),
                message=json.dumps(payload, indent=2, ensure_ascii=False),
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                execution_result=self.latest_execution_result,
                listing_ranking=self.latest_listing_ranking,
                json_payload=payload,
            )
        if lower == "transcript":
            return AgentTurn(
                state=self._current_state(),
                message=_render_transcript(self.transcript),
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
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
                    search_readiness=self.latest_readiness,
                    query_plan=self.latest_plan,
                    json_payload=self.current_state_payload(),
                )
            self.max_listings = max_listings
            self.pending_execution_confirmation = False
            self.proposed_execution_providers = ()
            return AgentTurn(
                state=self._current_state(),
                message=f"Max listings per provider set to {self.max_listings}.",
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
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
        clarification = self._readiness_followup()
        if clarification:
            return AgentTurn(
                state="needs_clarification",
                message=clarification,
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        if not self.latest_plan:
            return AgentTurn(
                state="blocked",
                message="No provider plan is available yet. Tell me what you are looking for first.",
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                json_payload=self.current_state_payload(),
            )
        return self._agent_led_planning_turn()

    def _execute_command(self) -> AgentTurn:
        if not self.current_intent or not self.latest_plan:
            return AgentTurn(
                state="blocked",
                message="Execution is blocked until there is a provider plan. Tell me what you are looking for first.",
                json_payload=self.current_state_payload(),
            )
        clarification = self._readiness_followup()
        if clarification:
            return AgentTurn(
                state="needs_clarification",
                message=clarification,
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        proposed_providers = self._recommended_execution_providers()
        if not proposed_providers:
            return AgentTurn(
                state="blocked",
                message="Execution is blocked because no executable provider is available for this plan.",
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        self.pending_execution_confirmation = True
        self.proposed_execution_providers = proposed_providers
        return AgentTurn(
            state="execution_confirmation_requested",
            message=self.render_execution_confirmation(),
            intent=self.current_intent,
            search_readiness=self.latest_readiness,
            query_plan=self.latest_plan,
            json_payload=self.current_state_payload(),
        )

    def _yes_command(self) -> AgentTurn:
        if not self.pending_execution_confirmation:
            return AgentTurn(
                state="blocked",
                message="There is no search awaiting confirmation yet. Tell me what you are looking for, or type `plan` if you want to review the current search.",
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        if not self.current_intent or not self.latest_plan:
            self.pending_execution_confirmation = False
            self.proposed_execution_providers = ()
            return AgentTurn(
                state="blocked",
                message="Execution is blocked because the current plan is missing.",
                json_payload=self.current_state_payload(),
            )

        executable_providers = self.proposed_execution_providers or self._recommended_execution_providers()
        if not executable_providers:
            self.pending_execution_confirmation = False
            return AgentTurn(
                state="blocked",
                message="Execution is blocked because no executable provider is available for this plan.",
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
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
            self.proposed_execution_providers = ()
            return AgentTurn(
                state="error",
                message=f"Search execution failed before provider results were returned: {exc}",
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )

        self.pending_execution_confirmation = False
        self.proposed_execution_providers = ()
        self.latest_execution_result = result

        records = list(getattr(result, "records", []) or [])
        hard_filtered = apply_hard_constraints(records, self.current_intent)
        self.latest_hard_excluded_records = hard_filtered.excluded_records
        self.latest_hard_exclusion_counts = hard_filtered.exclusion_counts
        self.latest_listing_ranking = None
        self.latest_ranking_error = ""
        if hard_filtered.records:
            try:
                ranking = self.listing_ranker(
                    self.current_intent,
                    self.latest_readiness,
                    hard_filtered.records,
                    client=self.client,
                    model=self.model,
                )
                self.latest_listing_ranking = _merge_deterministic_exclusions(
                    ranking,
                    hard_filtered.excluded_records,
                )
            except Exception as exc:
                self.latest_ranking_error = str(exc)
                if hard_filtered.excluded_records:
                    self.latest_listing_ranking = _merge_deterministic_exclusions(
                        ListingRankingResult(overall_summary="Listing ranking failed; deterministic exclusions are still shown."),
                        hard_filtered.excluded_records,
                    )
        elif hard_filtered.excluded_records:
            self.latest_listing_ranking = _merge_deterministic_exclusions(
                ListingRankingResult(overall_summary="All returned listings were removed by hard constraints."),
                hard_filtered.excluded_records,
            )

        return AgentTurn(
            state="executed",
            message=self.render_execution_result(result),
            intent=self.current_intent,
            search_readiness=self.latest_readiness,
            query_plan=self.latest_plan,
            execution_result=result,
            listing_ranking=self.latest_listing_ranking,
            json_payload=self.current_state_payload(),
        )

    def _no_command(self) -> AgentTurn:
        if not self.pending_execution_confirmation:
            return AgentTurn(
                state="blocked",
                message="Nothing is awaiting confirmation.",
                intent=self.current_intent,
                search_readiness=self.latest_readiness,
                query_plan=self.latest_plan,
                json_payload=self.current_state_payload(),
            )
        self.pending_execution_confirmation = False
        self.proposed_execution_providers = ()
        return AgentTurn(
            state="planned",
            message="Execution canceled. No search has run.",
            intent=self.current_intent,
            search_readiness=self.latest_readiness,
            query_plan=self.latest_plan,
            json_payload=self.current_state_payload(),
        )

    def _readiness_followup(self) -> str | None:
        if not self.current_intent:
            return None
        if not self.latest_readiness:
            if not self.current_intent.location:
                return "What larger city or metro area should I search in?"
            return None
        if self.current_intent.location and not _has_purpose_signal(self.current_intent):
            return "Is this just for you/private room/student/sublet, a regular rental/full rental with multiple roommates, or affordable/voucher/accessibility housing?"
        if self.latest_readiness.ready_to_search and self.latest_readiness.next_action != "ask_followup":
            return None
        questions = self.latest_readiness.followup_questions
        if not questions and not self.latest_readiness.ready_to_search:
            questions = ("What budget, room type or bedroom count, and move-in timing should I use to narrow this?",)
        if not questions:
            return None
        lines: list[str] = []
        if self.latest_readiness.reasoning_summary:
            lines.append(self.latest_readiness.reasoning_summary)
            lines.append("")
        if len(questions) == 1:
            lines.append(questions[0])
        else:
            lines.append("Two details would make this search much more useful:")
            lines.extend(f"- {question}" for question in questions[:2])
        return "\n".join(lines)

    def _agent_led_planning_turn(self) -> AgentTurn:
        proposed_providers = self._recommended_execution_providers()
        if proposed_providers:
            self.pending_execution_confirmation = True
            self.proposed_execution_providers = proposed_providers
            state = "execution_confirmation_requested"
        else:
            self.pending_execution_confirmation = False
            self.proposed_execution_providers = ()
            state = "planned"
        return AgentTurn(
            state=state,
            message=self.render_agent_led_plan(),
            intent=self.current_intent,
            search_readiness=self.latest_readiness,
            query_plan=self.latest_plan,
            json_payload=self.current_state_payload(),
        )

    def render_agent_led_plan(self) -> str:
        if not self.current_intent or not self.latest_plan:
            return "Tell me what kind of housing you are looking for."

        top_plan = self.latest_plan.provider_plans[0]
        proposed = self.proposed_execution_providers or self._recommended_execution_providers()
        lines = [
            _one_line_intent(self.current_intent),
            "",
            f"I’d start with {_provider_label(top_plan.provider)} because {_user_facing_reason(top_plan.provider)}",
        ]
        if self.latest_readiness and self.latest_readiness.reasoning_summary:
            lines.extend(["", self.latest_readiness.reasoning_summary])
        if self.latest_readiness and not self.latest_readiness.ready_to_recommend:
            lines.append("I can search, but I’ll treat the matches as options to verify rather than confident recommendations.")

        warnings = _user_facing_warnings(self.latest_plan)
        if warnings:
            lines.extend(["", *[f"Note: {warning}" for warning in warnings]])

        if proposed:
            provider_text = ", ".join(_provider_label(provider) for provider in proposed)
            lines.extend(
                [
                    "",
                    f"I can search {provider_text} now and return up to {self.max_listings} listings.",
                    "Want me to run it?",
                ]
            )
        else:
            lines.append("")
            lines.append("I can plan this, but I do not have an executable provider to run for it yet.")
        return "\n".join(lines)

    def _recommended_execution_providers(self) -> tuple[str, ...]:
        if not self.latest_plan:
            return ()
        executable_providers, _skipped = executable_provider_plan(self.latest_plan)
        executable = set(executable_providers)
        candidates = [
            provider_plan
            for provider_plan in self.latest_plan.provider_plans
            if provider_plan.provider in executable
        ]
        if not candidates:
            return ()
        top_score = candidates[0].score
        threshold = top_score * 0.7 if top_score > 0 else top_score
        selected = [
            provider_plan.provider
            for provider_plan in candidates
            if provider_plan.score >= threshold
        ]
        return tuple(selected[:2])

    def _planning_payload(self) -> dict[str, Any] | None:
        if not self.current_intent or not self.latest_plan:
            return None
        executable_providers, skipped = executable_provider_plan(self.latest_plan)
        return {
            "intent": _to_jsonable(self.current_intent),
            "search_readiness": _to_jsonable(self.latest_readiness),
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
                    "excluded_records_count": len(getattr(provider_result, "excluded_records", []) or []),
                    "exclusion_counts": _to_jsonable(getattr(provider_result, "exclusion_counts", None)),
                    "raw_output": _to_jsonable(getattr(provider_result, "raw_output", None)),
                    "csv_output": _to_jsonable(getattr(provider_result, "csv_output", None)),
                    "debug_artifacts": _to_jsonable(getattr(provider_result, "debug_artifacts", None)),
                }
                for provider_result in list(getattr(result, "provider_results", []) or [])
            ],
            "records": _to_jsonable(list(getattr(result, "records", []) or [])),
            "excluded_records": _to_jsonable(list(getattr(result, "excluded_records", []) or [])),
            "hard_excluded_records": _to_jsonable(self.latest_hard_excluded_records),
            "exclusion_counts": _to_jsonable(getattr(result, "exclusion_counts", None)),
            "hard_exclusion_counts": _to_jsonable(self.latest_hard_exclusion_counts),
            "errors": dict(getattr(result, "errors", {}) or {}),
        }

    def _current_state(self) -> str:
        if self.pending_execution_confirmation:
            return "execution_confirmation_requested"
        if self.latest_execution_result is not None:
            return "executed"
        if self.latest_plan is not None:
            clarification = self._readiness_followup() if self.current_intent else None
            return "needs_clarification" if clarification else "planned"
        if self.current_intent is not None:
            return "collecting"
        return "collecting"


def _has_purpose_signal(intent: HousingSearchIntent) -> bool:
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
        "neighborhoods": "Neighborhood preferences",
        "avoid_neighborhoods": "Avoid neighborhoods",
        "min_price": "Min price",
        "max_price": "Max price",
        "price_basis": "Price basis",
        "bedrooms": "Bedrooms",
        "bedroom_min": "Bedroom min",
        "bedroom_max": "Bedroom max",
        "bathrooms": "Bathrooms",
        "bathroom_min": "Bathroom min",
        "property_types": "Property types",
        "type_of_places": "Place type",
        "pet_policy": "Pet policy",
        "pet_policy_negated": "Pet policy exclusions",
        "furnished": "Furnished",
        "move_in_date": "Move in",
        "move_out_date": "Move out",
        "lease_length": "Lease length",
        "campus_or_school": "Campus/school",
        "commute_target": "Commute target",
        "max_commute_minutes": "Max commute minutes",
        "roommate_count": "Roommate count",
        "amenities": "Amenities",
        "required_amenities": "Required amenities",
        "preferred_amenities": "Preferred amenities",
        "dealbreakers": "Dealbreakers",
        "safety_priority": "Safety priority",
        "student_priority": "Student priority",
        "sort": "Sort",
        "section8": "Section 8",
        "income_restricted": "Income restricted",
        "wheelchair_accessible": "Wheelchair accessible",
        "utilities_included": "Utilities included",
        "washer_dryer": "Washer/dryer",
        "keyword": "Keyword",
        "intent_kind": "Intent kind",
        "flexibility_notes": "Flexibility",
        "notes": "Notes",
    }
    lines: list[str] = []
    for key, label in labels.items():
        value = data.get(key)
        if value is None or value == "" or value == [] or value is False:
            continue
        if key in {"price_basis", "safety_priority", "student_priority"} and value == "unknown":
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value)
        else:
            rendered = str(value)
        lines.append(f"{label}: {rendered}")
    return lines or ["No concrete filters yet"]


def _readiness_summary_lines(readiness: SearchReadiness) -> list[str]:
    lines = [
        f"Ready to search: {readiness.ready_to_search}",
        f"Ready to recommend: {readiness.ready_to_recommend}",
        f"Confidence: {readiness.confidence}",
    ]
    if readiness.missing_required_fields:
        lines.append("Missing: " + ", ".join(readiness.missing_required_fields))
    if readiness.hard_constraints:
        lines.append("Hard constraints: " + ", ".join(readiness.hard_constraints))
    if readiness.soft_preferences:
        lines.append("Soft preferences: " + ", ".join(readiness.soft_preferences))
    if readiness.safe_assumptions:
        lines.append("Safe assumptions: " + ", ".join(readiness.safe_assumptions))
    if readiness.reasoning_summary:
        lines.append("Summary: " + readiness.reasoning_summary)
    return lines


def _ranked_listing_line(listing: Any) -> str:
    title = getattr(listing, "title", "") or "Untitled listing"
    url = getattr(listing, "url", "")
    score = getattr(listing, "fit_score", 0)
    why = getattr(listing, "why_it_fits", "")
    concerns = tuple(getattr(listing, "concerns", ()) or ())
    missing = tuple(getattr(listing, "missing_info", ()) or ())
    suffixes: list[str] = [f"fit {score:g}/100"]
    if why:
        suffixes.append(why)
    if missing:
        suffixes.append("missing: " + ", ".join(missing[:3]))
    if concerns:
        suffixes.append("concerns: " + ", ".join(concerns[:3]))
    if url:
        suffixes.append(url)
    return f"{title} ({'; '.join(suffixes)})"


def _merge_deterministic_exclusions(
    ranking: ListingRankingResult,
    excluded_records: Sequence[Mapping[str, Any]],
) -> ListingRankingResult:
    if not excluded_records:
        return ranking
    deterministic = tuple(_excluded_record_to_ranked_listing(record) for record in excluded_records)
    return ListingRankingResult(
        recommended=ranking.recommended,
        needs_verification=ranking.needs_verification,
        excluded=(*deterministic, *ranking.excluded),
        overall_summary=ranking.overall_summary,
        followup_suggestions=ranking.followup_suggestions,
        raw_response=ranking.raw_response,
    )


def _excluded_record_to_ranked_listing(record: Mapping[str, Any]) -> RankedListing:
    raw_reasons = record.get("excluded_reasons", ()) or ()
    if isinstance(raw_reasons, str):
        reasons = (raw_reasons,)
    else:
        reasons = tuple(str(reason) for reason in raw_reasons)
    reason = str(record.get("excluded_reason") or (reasons[0] if reasons else "Hard constraint failed."))
    return RankedListing(
        listing_id=str(record.get("listing_id") or record.get("id") or ""),
        title=str(record.get("title") or record.get("name") or "Untitled listing"),
        url=str(record.get("listing_url") or record.get("url") or record.get("detail_url") or ""),
        fit_score=0,
        matched_constraints=(),
        missing_info=(),
        concerns=reasons or (reason,),
        why_it_fits=reason,
        provider=str(record.get("provider") or record.get("source") or ""),
        raw=dict(record),
    )


def _broaden_retry_suggestion(
    exclusion_counts: Mapping[str, int],
    intent: HousingSearchIntent | None,
) -> str:
    if not exclusion_counts or not intent:
        return ""
    top_reason = max(exclusion_counts.items(), key=lambda item: item[1])[0]
    if top_reason == "max_price" and intent.max_price:
        relaxed = int(round(intent.max_price * 1.2 / 50) * 50)
        return f"I found 0 listings under ${intent.max_price:,}. Want me to retry at ${relaxed:,}, or remove another requirement?"
    if top_reason in {"bedrooms", "bedroom_min", "bedroom_max"}:
        return "I found 0 listings after the bedroom filter. Want me to loosen the bedroom requirement?"
    if top_reason in {"required_amenities", "washer_dryer", "utilities_included", "wheelchair_accessible"}:
        return "I found 0 listings after amenity filters. Want me to retry without one must-have?"
    return "I found 0 listings after applying filters. Want me to broaden the search?"


def _why_line(reasons: Sequence[str]) -> str:
    profile_reasons = [reason for reason in reasons if "fit" in reason]
    if profile_reasons:
        return profile_reasons[0]
    useful_reasons = [reason for reason in reasons if "verified source" in reason or "unsupported" in reason]
    if useful_reasons:
        return "; ".join(useful_reasons[:2])
    return reasons[0] if reasons else "ranked by provider capability fit"


def _provider_label(provider: str) -> str:
    labels = {
        RENTALSOURCE: "RentalSource",
        OHANA: "Ohana",
        AFFORDABLEHOUSING: "AffordableHousing",
    }
    return labels.get(provider, provider)


def _user_facing_reason(provider: str) -> str:
    if provider == RENTALSOURCE:
        return "it is the best fit for general apartment, house, and rental searches."
    if provider == OHANA:
        return "it is the best fit for furnished rooms, student housing, and sublets."
    if provider == AFFORDABLEHOUSING:
        return "it is the best fit for voucher, income-restricted, and affordable housing searches."
    return "it ranked highest for this search."


def _proposal_sentence(providers: Sequence[str], max_listings: int) -> str:
    provider_text = ", ".join(_provider_label(provider) for provider in providers)
    return f"I can search {provider_text} now and return up to {max_listings} listings. Want me to run it?"


def _one_line_intent(intent: HousingSearchIntent) -> str:
    pieces: list[str] = []
    if intent.intent_kind == "student_sublet":
        if intent.campus_or_school:
            pieces.append(f"student summer housing near {intent.campus_or_school}")
        else:
            pieces.append("student/sublet housing")
    elif intent.type_of_places:
        pieces.append(", ".join(intent.type_of_places).lower())
    elif intent.property_types:
        pieces.append(", ".join(intent.property_types).lower())
    elif intent.intent_kind and intent.intent_kind != "unknown":
        pieces.append(intent.intent_kind.replace("_", " "))
    else:
        pieces.append("housing")

    if intent.location:
        pieces.append(f"in {intent.location}")
    if intent.max_price:
        pieces.append(f"under ${intent.max_price:,}")
    if intent.bedrooms:
        pieces.append(f"with {intent.bedrooms} bedroom(s)")
    elif intent.bedroom_min:
        pieces.append(f"with at least {intent.bedroom_min} bedroom(s)")
    if intent.furnished is True:
        pieces.append("furnished")
    if intent.pet_policy and not intent.pet_policy_negated:
        pieces.append("pet-friendly")

    return "I understand you’re looking for " + " ".join(pieces) + "."


def _user_facing_warnings(query_plan: QueryPlan) -> list[str]:
    warnings: list[str] = []
    date_filters = {"move_in_date", "move_out_date"}
    if any(
        date_filters.intersection(provider_plan.report.unknown_unverified)
        or date_filters.intersection(provider_plan.report.unsupported)
        for provider_plan in query_plan.provider_plans
    ):
        warnings.append("Date filters may need to be checked after results because they are not verified source filters everywhere.")
    top_provider = query_plan.provider_plans[0].provider if query_plan.provider_plans else ""
    if top_provider == OHANA:
        warnings.append("Ohana may require a saved login session.")
    return warnings


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
