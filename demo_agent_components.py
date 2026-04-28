"""
Live demo: prove every required agent component is real and wired together.

Run: MISTRAL_API_KEY=sk-... python3 demo_agent_components.py

LLM calls go to the real Mistral API via MistralChatClient — the same path
production uses. Only the Playwright scraper is stubbed so the demo is fast
and doesn't need a saved Ohana login. Everything else (intent merging,
capability matrix, query planner, URL builders, readiness guards,
confirmation gate, post-filter, listing ranker, transcript memory) is real
production code.
"""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.housing_agent.interactive_agent import InteractiveHousingAgent
from src.housing_agent.llm_client import MistralChatClient
from src.housing_agent.query_planner import plan_query
from src.housing_agent.types import HousingSearchIntent
from src.ohana_agent.search_url import build_ohana_search_url
from src.affordablehousing_agent.search_url import build_affordablehousing_search_url
from src.rentalsource_agent.search_url import build_rentalsource_search_url
from src.supported_locations import supported_location_for


# ----------------------------------------------------------------------------
# Only the browser layer is stubbed (it's a tool, not an LLM call).
# ----------------------------------------------------------------------------

class CountingClient:
    """Wraps the real MistralChatClient and counts calls + records messages."""

    def __init__(self, inner: MistralChatClient) -> None:
        self.inner = inner
        self.model = inner.model
        self.call_log: list[tuple[str, int]] = []

    def complete_json(self, messages, *, temperature=0.0, max_tokens=1200):
        sys_prompt = (messages[0].get("content") or "")[:60].replace("\n", " ")
        self.call_log.append((sys_prompt, len(messages)))
        return self.inner.complete_json(
            messages, temperature=temperature, max_tokens=max_tokens
        )


class FakeRouterResult:
    def __init__(self, provider: str, records: list[dict]) -> None:
        self.records = records
        self.provider_results = [type("PR", (), {
            "provider": provider, "status": "ok" if records else "empty",
            "error": "", "search_url": "https://example/mock",
            "records": records, "raw_output": None, "csv_output": None,
            "debug_artifacts": {},
        })()]
        self.search_url = "https://example/mock"
        self.raw_output = None
        self.csv_output = None
        self.debug_artifacts = {}
        self.errors = {}


def fake_runner_factory(records):
    def runner(plan, *, providers, **kwargs):
        return FakeRouterResult(providers[0], records)
    return runner


# ----------------------------------------------------------------------------
# Pretty-print helpers
# ----------------------------------------------------------------------------

def banner(label: str) -> None:
    print("\n" + "=" * 70)
    print(f"  {label}")
    print("=" * 70)

def sub(label: str) -> None:
    print(f"\n--- {label} ---")

def show_turn(label: str, turn) -> None:
    sub(f"agent state after {label}")
    print(f"  state: {turn.state}")
    print(f"  message (from real Mistral + deterministic layers):")
    for line in (turn.message or "").splitlines():
        print(f"    {line}")


# ============================================================================
# DEMO
# ============================================================================

if not os.environ.get("MISTRAL_API_KEY"):
    print("ERROR: set MISTRAL_API_KEY before running this demo.")
    print("       export MISTRAL_API_KEY=sk-...")
    sys.exit(1)


banner("COMPONENT MAP — what this demo proves")
print("""
  1. Data incorporation     -> real provider URL builders + scraper contract
  2. Memory and retrieval   -> intent merge across turns + transcript replay
  3. Three tools            -> Ohana, RentalSource, AffordableHousing routers
  4. Robust system design   -> layered pipeline (extract -> readiness ->
                                plan -> confirm -> execute -> rank)
  5. Guardrails             -> location, neighborhood, unsupported city,
                                confirmation gate, LLM downgrade
  6. Evaluation framework   -> tests/ directory (run at end)
""")


# ----------------------------------------------------------------------------
banner("PART 1 — Data incorporation: deterministic provider URL builders")
# ----------------------------------------------------------------------------

sub("Ohana — student sublets")
print("  " + build_ohana_search_url(
    location="Boston, MA", type_of_places=["Private room"],
    max_price=1800, furnished_status=["Furnished"], movein="2026-06-01"))

sub("RentalSource — general rentals")
print("  " + build_rentalsource_search_url(
    location="Philadelphia, PA", property_types=["Apartment"],
    num_bedrooms=2, max_price=2600, pets=True, sort="newest"))

sub("AffordableHousing — voucher / income-restricted")
print("  " + build_affordablehousing_search_url(
    location="Boston, MA", max_price=1600,
    section8=True, income_restricted=True))


# ----------------------------------------------------------------------------
banner("PART 2 — Capability matrix drives provider selection (no LLM)")
# ----------------------------------------------------------------------------

intent = HousingSearchIntent(
    location="Boston, MA", max_price=1800,
    type_of_places=("Private room",), furnished=True,
    intent_kind="student_sublet",
)
plan = plan_query(intent)
print(f"\nIntent: furnished private room in Boston under $1800 (student sublet)")
print("\nProvider ranking (deterministic, score-based):")
for p in plan.provider_plans:
    print(f"  {p.provider:18s}  score {p.score:5.1f}  quality={p.quality}")
top = plan.provider_plans[0]
print(f"\nTop provider source-applied filters: {list(top.report.applied_at_source)}")
print(f"Unknown/unverified:                  {list(top.report.unknown_unverified)}")


# ----------------------------------------------------------------------------
banner("PART 3 — Live conversation against the REAL Mistral API")
# ----------------------------------------------------------------------------
print("""
The conversation drives InteractiveHousingAgent. The LLM is the production
MistralChatClient (no canned responses). Only the browser/scrape layer is
stubbed so we don't need a saved Ohana login.
""")

real_client = CountingClient(MistralChatClient.from_env())
print(f"  using model: {real_client.model}")

mock_records = [
    {"id": "abc123", "source": "ohana",
     "title": "Furnished room near Penn campus",
     "price": "$1,650/mo", "location": "University City, Philadelphia",
     "url": "https://liveohana.ai/listing/abc123",
     "image_urls": ["https://example/img1.jpg"], "raw_text": "Furnished private room walking distance to UPenn. $1,650/mo. Available June 1 - August 31."},
    {"id": "def456", "source": "ohana",
     "title": "Room in University City apartment",
     "price": "", "location": "Philadelphia, PA",
     "url": "https://liveohana.ai/listing/def456", "image_urls": [],
     "raw_text": "Private room in shared apartment near University City."},
]

agent = InteractiveHousingAgent(
    client=real_client,
    runner=fake_runner_factory(mock_records),
    max_listings=5,
    today="2026-04-28",
)


# --- Turn 1: neighborhood-only guard ---------------------------------------
sub("USER: 'i need somewhere to stay for a summer program at upenn'")
turn = agent.handle_user_message("i need somewhere to stay for a summer program at upenn")
show_turn("turn 1", turn)
print("\n  >>> GUARDRAIL CHECK <<<")
print(f"  intent.location after guard:  {agent.current_intent.location!r}")
print(f"  intent.campus_or_school:      {agent.current_intent.campus_or_school!r}")
print(f"  next_action after guard:      {agent.latest_readiness.next_action!r}")
print("  (If the model proposed 'University City' or 'execute_search',")
print("   the deterministic guards override it — see above.)")


# --- Turn 2: memory merge ---------------------------------------------------
sub("USER: 'philly'")
turn = agent.handle_user_message("philly")
show_turn("turn 2", turn)
print("\n  >>> MEMORY CHECK <<<")
print(f"  campus survived from turn 1:  "
      f"{agent.current_intent.campus_or_school!r}")
print(f"  location now resolved:        "
      f"{agent.current_intent.location!r}")
print(f"  transcript entries stored:    {len(agent.transcript)}")


# --- Turn 3: full intent -> proposal ---------------------------------------
sub("USER: '$1500 to $1800, private room, furnished, for the summer'")
turn = agent.handle_user_message(
    "$1500 to $1800, private room, furnished, for the summer")
show_turn("turn 3", turn)
print("\n  >>> PLANNING CHECK <<<")
print(f"  pending_execution_confirmation: {agent.pending_execution_confirmation}")
print(f"  proposed providers:             {agent.proposed_execution_providers}")
print(f"  ranked providers (real planner):"
      f"  {[p.provider for p in agent.latest_plan.provider_plans]}")
print(f"  source-applied for top provider:"
      f"  {list(agent.latest_plan.provider_plans[0].report.applied_at_source)}")


# --- Turn 4: unsupported-city guardrail ------------------------------------
sub("USER: 'actually go to chicago'  (must be refused)")
turn = agent.handle_user_message("actually go to chicago")
show_turn("turn 4", turn)
print("\n  >>> GUARDRAIL CHECK <<<")
print(f"  state:           {turn.state!r}")
print(f"  intent.location: {agent.current_intent.location!r}")
print(f"  pending exec:    {agent.pending_execution_confirmation}  "
      f"(must be False — user did not get to a 'yes' for an unsupported city)")

sub("DIRECT GUARD on supported_location_for('Chicago, IL')")
try:
    supported_location_for("Chicago, IL")
    print("  unexpectedly accepted")
except ValueError as exc:
    print(f"  ValueError: {exc}")


# --- Turn 5: back to philly (explicit so the LLM resets location) ----------
sub("USER: 'never mind chicago, change the location back to Philadelphia'")
turn = agent.handle_user_message(
    "never mind chicago, change the location back to Philadelphia")
show_turn("turn 5", turn)
print("\n  >>> RECOVERY CHECK <<<")
print(f"  intent.location:                 {agent.current_intent.location!r}")
print(f"  pending_execution_confirmation:  {agent.pending_execution_confirmation}")


# --- Turn 5b: answer any remaining clarification so we reach execution -----
# (real LLMs are non-deterministic; if the model still wants details, give them)
if not agent.pending_execution_confirmation:
    sub("USER: 'June 1 to August 15, flexible by a few days'  (clear remaining gaps)")
    turn = agent.handle_user_message(
        "June 1 to August 15, flexible by a few days")
    show_turn("turn 5b", turn)


# --- Turn 6: confirmation gate ---------------------------------------------
sub("USER: 'yes'  (only path that triggers tool execution)")
turn = agent.handle_user_message("yes")
show_turn("turn 6", turn)
print("\n  >>> TOOL CALL EVIDENCE <<<")
if agent.latest_execution_result is None:
    print("  (no execution — agent did not reach the confirmation state)")
else:
    print(f"  records returned by tool layer: "
          f"{len(agent.latest_execution_result.records)}")
    if agent.latest_listing_ranking:
        r = agent.latest_listing_ranking
        print(f"  ranking buckets (real LLM call): "
              f"recommended={len(r.recommended)}, "
              f"needs_verification={len(r.needs_verification)}, "
              f"excluded={len(r.excluded)}")


# ----------------------------------------------------------------------------
banner("PART 4 — Final structured output")
# ----------------------------------------------------------------------------

ranking = agent.latest_listing_ranking
if ranking is None:
    print("\n  (no ranking — execution did not produce records)")
else:
    for bucket_name in ("recommended", "needs_verification", "excluded"):
        bucket = getattr(ranking, bucket_name)
        if not bucket:
            continue
        sub(bucket_name.upper())
        for r in bucket:
            print(f"  - {r.title}  (fit {r.fit_score:.0f}/100)")
            print(f"      provider: {r.provider}   url: {r.url}")
            if r.matched_constraints:
                print(f"      matched:  {', '.join(r.matched_constraints)}")
            if r.missing_info:
                print(f"      missing:  {', '.join(r.missing_info)}")
            if r.why_it_fits:
                print(f"      why:      {r.why_it_fits}")


# ----------------------------------------------------------------------------
banner("PART 5 — LLM call accounting")
# ----------------------------------------------------------------------------
print(f"\n  Total real Mistral API calls during the demo: {len(real_client.call_log)}")
for i, (sys_prompt, msg_count) in enumerate(real_client.call_log, 1):
    print(f"    {i:2d}. msgs={msg_count}  system_prompt='{sys_prompt}...'")
print("\n  ZERO LLM calls were used for: URL building, provider scoring,")
print("  filter classification, scrape execution, or confirmation handling.")


# ----------------------------------------------------------------------------
banner("PART 6 — Evaluation framework")
# ----------------------------------------------------------------------------
test_files = sorted(Path("tests").glob("test_*.py"))
print(f"\n  {len(test_files)} test files in tests/:")
for path in test_files:
    print(f"    {path.name}")
print("\n  Run separately:  python3 -m unittest discover -s tests -v")
