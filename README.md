# Housing Search Agent — Provider-Aware Browser Tools

This is a small, test-first housing search project for logging into housing providers with your own account when needed, running searches, extracting visible listing-card information, and saving results to files. It also includes an LLM-assisted housing chat loop, deterministic provider capability/query planning, explicit execution confirmation, and post-result listing fit ranking.

It intentionally does **not** bypass Cloudflare, CAPTCHAs, login protections, private APIs, or rate limits. Use it only with an account you are allowed to use and only at low, human-like volume.

Supported search markets are currently Boston, MA; New York, NY; Washington, DC; and Philadelphia, PA.

## What it does

1. Checks that each chat message is on-topic for rental housing before updating search state.
2. Extracts or updates a provider-neutral `HousingSearchIntent` from user language.
3. Evaluates search readiness: what is required, what is flexible, and whether a follow-up is useful.
4. Builds a deterministic provider-aware query plan for:
   - Ohana
   - RentalSource
   - AffordableHousing.com
5. Shows the user which provider should run first and why.
6. Executes only after explicit confirmation.
7. Routes execution through the deterministic provider router, not through the LLM.
8. Ranks returned listings against the user intent without inventing missing facts.
9. Saves scraper outputs:
   - raw JSONL to `data/raw/`
   - readable CSV to `data/processed/`
   - screenshot + HTML debug files to `data/debug/`

The LLM is used for topic checks, language understanding, search readiness, and result-fit explanation. Deterministic code owns provider ranking, URL/query construction, confirmation state, and scraper execution.

## Folder structure

```text
(project root)/
  auth/
    ohana_state.json              # created after login; gitignored
    affordablehousing_state.json  # created after login; gitignored
    rentalsource_state.json       # created after login; gitignored

  data/
    raw/                          # JSONL results (housing_provider_results_*.jsonl)
    processed/                    # CSV results  (housing_provider_results_*.csv)
    debug/                        # screenshot + HTML snapshots

  src/
    housing_agent/
      intent_extractor.py         # Mistral-backed provider-neutral intent extraction
      intent_guards.py            # hard-constraint guards on extracted intent
      readiness_evaluator.py      # Mistral-backed search readiness/follow-up policy
      listing_ranker.py           # Mistral-backed listing fit ranking after execution
      listing_parsing.py          # normalizes raw listing records for ranking
      llm_client.py               # small stdlib Mistral chat-completion client
      location_scope.py           # maps user location strings to supported markets
      post_filter.py              # deterministic hard-constraint post-filter
      provider_capabilities.py    # provider capability matrix
      query_planner.py            # deterministic query planning/reporting
      search_app.py               # one-shot plan/execute app API
      interactive_agent.py        # stateful terminal chat controller
      topic_guard.py              # on-topic check for incoming messages
      ui_server.py                # local stdlib web UI server
      ui_static/                  # HTML/CSS/JS for the browser UI
      types.py                    # shared intent/readiness/query/ranking dataclasses

    ohana_agent/
      browser.py                  # Playwright browser/session helpers
      config.py                   # settings and paths
      extractor.py                # DOM extraction logic
      listing_api.py              # Ohana detail-API coordinate fetcher
      provider_router.py          # deterministic multi-provider router
      parsing.py                  # field normalization / regex guesses
      search_runner.py            # importable Ohana scraping tool
      search_url.py               # Ohana URL builder
      storage.py                  # JSONL + CSV writers

    affordablehousing_agent/
      browser.py
      config.py
      detail.py                   # detail-page address/coordinate enrichment
      extractor.py
      parsing.py
      search_runner.py
      search_url.py               # AffordableHousing.com SEO URL builder
      storage.py

    rentalsource_agent/
      browser.py
      config.py
      detail.py                   # detail-page JSON-LD enrichment
      extractor.py
      parsing.py
      search_runner.py
      search_url.py               # RentalSource URL builder
      storage.py

    supported_locations.py        # canonical supported city/neighborhood map

  tests/                          # unittest suite

  run_housing_ui.py               # local browser UI (opens http://127.0.0.1:8765)
  run_housing_chat.py             # interactive agent-user loop (terminal)
  run_housing_search.py           # one-shot plan/execute flow
  run_housing_intent.py           # intent extraction + query plan only
  run_ohana_search.py             # run/extract Ohana search directly
  run_rentalsource_search.py      # run/extract RentalSource search directly
  run_affordablehousing_search.py # run/extract AffordableHousing search directly
  save_ohana_login.py             # save Ohana login session
  save_rentalsource_login.py      # save RentalSource login session
  save_affordablehousing_login.py # save AffordableHousing login session
  demo_agent_components.py        # standalone component demo
  selectors.ohana.json            # editable Ohana DOM selectors
  selectors.affordablehousing.json
  selectors.rentalsource.json
  selectors.example.json          # template / reference
  requirements.txt
  .env.example
  .gitignore
```

## Setup

From inside this folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Optional: copy `.env.example` to `.env` and edit defaults:

```bash
cp .env.example .env
```

Export your Mistral API key before running any LLM-backed command:

```bash
export MISTRAL_API_KEY="your-key-here"
```

For the model, the default is `mistral-small-latest`. You can override it:

```bash
export MISTRAL_MODEL=mistral-small-latest
```

No extra Python package is required for the LLM layers; the project uses the small stdlib Mistral client in `src/housing_agent/llm_client.py`.

## Before starting the UI — warm up each provider

Run a quick extraction from each provider before starting the chat UI. This verifies browser sessions and populates `data/` so the UI has something to show immediately.

**Ohana** (requires a saved login session — see [Step 1](#step-1--save-your-ohana-login-session)):

```bash
python run_ohana_search.py \
  --search-url "https://liveohana.ai/" \
  --manual-search \
  --max-listings 20 \
  --keep-open
```

**AffordableHousing.com** (login optional for public searches):

```bash
python run_affordablehousing_search.py \
  --search-url "https://www.affordablehousing.com/boston-ma/" \
  --manual-search \
  --max-listings 20 \
  --keep-open
```

**RentalSource** (public; no login needed):

```bash
python run_rentalsource_search.py \
  --location "Boston, MA" \
  --property-types Apartment \
  --max-listings 20
```

All three write results to `data/raw/`, `data/processed/`, and `data/debug/`.

## Local browser UI

Once the providers have run at least once, start the UI:

```bash
export MISTRAL_API_KEY="your-key-here"
python run_housing_ui.py --max-listings 5 --fetch-listing-api
```

Then open:

```text
http://127.0.0.1:8765
```

The UI wraps `InteractiveHousingAgent` and does not call provider scrapers directly. A search only runs after the agent has proposed a plan and the user clicks `Run Search` or replies `yes`. The UI renders artifact links from `data/debug/`, `data/raw/`, and `data/processed/`, including provider search-page screenshots saved by the scrapers.

## Interactive housing chat (terminal)

Use the chat agent for the full product flow without a browser:

```bash
export MISTRAL_API_KEY="your-key-here"
python run_housing_chat.py --max-listings 5
```

Example:

```text
> i need to find somewhere to stay for a summer program at upenn
```

The agent updates a merged `HousingSearchIntent`, evaluates whether enough information is present, asks at most a small number of useful follow-up questions, then proposes the best provider to run first. Execution requires a clear confirmation:

```text
yes
```

Useful commands inside the chat:

```text
help
show
plan
json
transcript
max-listings 3
reset
quit
```

`json` is debug-only and shows the current intent, readiness object, provider plan, pending confirmation state, execution result, and listing ranking state.

## Agent architecture

The safe agent flow is:

```text
user conversation
  -> LLM topic guard: is this message rental-housing related?
  -> LLM updates full merged HousingSearchIntent
  -> intent guards apply hard constraints
  -> LLM evaluates SearchReadiness
  -> deterministic query planner ranks providers and explains filter application
  -> user confirms execution
  -> deterministic provider router runs executable scrapers
  -> deterministic post-filter applies hard constraints to returned listings
  -> LLM ranks returned listings against the intent
```

Hard boundary:

- The LLM does **not** call scrapers.
- The LLM does **not** build provider URLs.
- The LLM does **not** choose browser flags or execution commands.
- Execution goes through `src.ohana_agent.provider_router.run_provider_searches`.
- Provider-specific CLI tools remain available for direct testing.

## Step 1 — Save your Ohana login session

```bash
python save_ohana_login.py --start-url "https://liveohana.ai/"
```

A browser will open. Log in normally. When you can see your logged-in account/search page, return to the terminal and press ENTER.

This creates:

```text
auth/ohana_state.json
```

Do **not** commit that file to GitHub.

## Step 2 — Run a manual test search

Start here first. This is the most reliable testing path because you manually perform the search in the browser, then the script extracts whatever results are visible.

```bash
python run_ohana_search.py \
  --search-url "https://liveohana.ai/" \
  --manual-search \
  --max-listings 20 \
  --keep-open
```

When the browser opens:

1. Navigate/search/filter however you normally would on Ohana.
2. Wait until the result cards are visible.
3. Return to the terminal and press ENTER.
4. The script extracts visible cards and saves files.

Outputs appear in:

```text
data/raw/housing_provider_results_YYYYMMDD_HHMMSS.jsonl
data/processed/housing_provider_results_YYYYMMDD_HHMMSS.csv
data/debug/search_page.png
data/debug/search_page.html
```

## Step 3 — Try automated search

After manual extraction works, you can try automated search input filling:

```bash
PYTHONPATH=src python -u run_ohana_search.py \
  --location "Boston, MA, USA" \
  --movein "May 1, 2026" \
  --moveout "May 31, 2026" \
  --property-types Apartment House \
  --type-of-places "Private room" \
  --num-bedrooms 1 \
  --min-price 1000 \
  --max-price 3000 \
  --selectors-file selectors.ohana.json \
  --max-listings 15 \
  --fetch-listing-api \
  --scrolls 0
```

If the script cannot find the search box, it will ask you to do the search manually — update `selectors.ohana.json` if that happens.

Ohana only writes exact coordinates when `--fetch-listing-api` is enabled and a real `/listing/...` detail URL is available. Each output record includes `coordinates_status` and `coordinates_source` so missing coordinates are explicit instead of silent.

## Query planning layer

The reusable integration point is layered: extract a provider-neutral structured intent, inspect provider capability/query quality, then call the router explicitly.

```python
from src.housing_agent import HousingSearchIntent, plan_query

intent = HousingSearchIntent(
    location="Boston, MA",
    max_price=1800,
    bedrooms=1,
    type_of_places=("Private room",),
    furnished=True,
    intent_kind="student_sublet",
)

query_plan = plan_query(intent)
print(query_plan.ranked_provider_names)
print(query_plan.for_provider("ohana").report.applied_at_source)
```

Provider scraping still happens through provider-specific CLIs or the deterministic router in `src.ohana_agent.provider_router`. Conversational code should target the intent/readiness/query-planning APIs and call only the deterministic provider router for execution.

To use Mistral for intent extraction without scraping:

```bash
export MISTRAL_API_KEY="your-key-here"
python run_housing_intent.py "furnished private room in Boston under $1800 for June 2026"
```

For the product-facing search flow, use `run_housing_search.py`. By default it only plans the search and prints the extracted intent, ranked providers, query quality, source-applied filters, unsupported/unverified filters, and execution warnings:

```bash
python run_housing_search.py "I need a furnished private room in Boston under 1800 for the summer"
```

Scraping is opt-in:

```bash
python run_housing_search.py "I need a furnished private room in Boston under 1800 for the summer" --execute --max-listings 5
```

## AffordableHousing.com tool

Save an optional login session (public searches work without it):

```bash
python save_affordablehousing_login.py --start-url "https://www.affordablehousing.com/"
```

Run a manual extraction test:

```bash
python run_affordablehousing_search.py \
  --search-url "https://www.affordablehousing.com/boston-ma/" \
  --manual-search \
  --max-listings 20 \
  --keep-open
```

Or build an AffordableHousing.com SEO search URL from CLI filters:

```bash
python run_affordablehousing_search.py \
  --location "Boston, MA" \
  --property-types Apartment \
  --selectors-file selectors.affordablehousing.json \
  --max-listings 20
```

To enrich extracted cards with exact detail-page address and coordinates:

```bash
python run_affordablehousing_search.py \
  --location "Boston, MA" \
  --property-types Apartment \
  --max-listings 10 \
  --fetch-listing-detail
```

Outputs appear in `data/raw/`, `data/processed/`, and `data/debug/` with an `affordablehousing` prefix in the debug files.

## RentalSource tool

Save an optional login session (listings are public):

```bash
python save_rentalsource_login.py --start-url "https://www.rentalsource.com/"
```

Run a filtered search:

```bash
python run_rentalsource_search.py \
  --location "Boston, MA" \
  --property-types Apartment \
  --num-bedrooms 1 \
  --num-bathrooms 1 \
  --min-price 1000 \
  --max-price 3000 \
  --sort price \
  --max-listings 20
```

The same manual-search and keep-open workflow works here:

```bash
python run_rentalsource_search.py \
  --search-url "https://www.rentalsource.com/boston-ma/" \
  --manual-search \
  --max-listings 20 \
  --keep-open
```

To enrich extracted cards with detail-page JSON-LD fields (exact address, latitude, longitude, beds, baths, price range):

```bash
python run_rentalsource_search.py \
  --location "Boston, MA" \
  --max-listings 10 \
  --fetch-listing-detail
```

Coordinate fields are explicit in all provider outputs: `listing_latitude`, `listing_longitude`, `coordinates_status`, `coordinates_source`.

## Updating selectors

Open:

```text
data/debug/search_page.html
```

Find the listing card HTML and update the relevant selectors file (`selectors.ohana.json`, `selectors.affordablehousing.json`, or `selectors.rentalsource.json`), especially:

```json
"result_card_selectors": [
  "[data-testid*='listing' i]",
  "[class*='listing' i]",
  "[class*='card' i]",
  "article"
]
```

## Example output record

```json
{
  "id": "7cc9b46c8c0e0b9d",
  "source": "ohana",
  "title": "Room in University City apartment",
  "price": "$1,250/mo",
  "location": "Philadelphia, PA",
  "dates": "May 15 - Aug 20",
  "bedrooms": "1 bed",
  "url": "https://liveohana.ai/...",
  "image_urls": ["https://..."],
  "scraped_at": "2026-04-26T12:00:00+00:00",
  "raw_text": "Full visible listing card text..."
}
```

## Automated tests

Run the automated tests with:

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
python3 -m unittest discover -s tests -v
```

Live browser scrape tests are skipped by default. To opt in:

```bash
RUN_LIVE_SCRAPE_TESTS=1 python3 -m unittest discover -s tests -v
```

Live Mistral tests are opt-in:

```bash
export MISTRAL_API_KEY="your-key-here"
RUN_LIVE_LLM_TESTS=1 python3 -m unittest tests.test_intent_extractor -v
```

Or run all live tests at once:

```bash
export MISTRAL_API_KEY="your-key-here"
python3 run_live_llm_tests.py
```

For a narrower local readiness check that runs only the live scrape tests:

```bash
python3 run_live_scrape_tests.py --install-chromium
```

## Common issues

### `ModuleNotFoundError: No module named 'playwright'`

Make sure your virtual environment is active and dependencies are installed:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

### No results extracted

Check:

```text
data/debug/search_page.png
data/debug/search_page.html
```

If the screenshot does not show results, run again with `--manual-search` and make sure results are visible before pressing ENTER.

If the screenshot shows results but CSV is empty, update `result_card_selectors` in the relevant selectors file.

### Login expired

Run the appropriate save-login script and log in again:

```bash
python save_ohana_login.py
python save_affordablehousing_login.py
python save_rentalsource_login.py
```

## Recommended testing workflow

1. Run `save_ohana_login.py`.
2. Run `run_ohana_search.py --manual-search --keep-open`.
3. Run `run_affordablehousing_search.py --manual-search --keep-open`.
4. Run `run_rentalsource_search.py --location "Boston, MA" --max-listings 20`.
5. Check the CSVs in `data/processed/`.
6. Check `data/debug/` HTML if extraction is wrong and tighten selectors.
7. Start `run_housing_ui.py` and open `http://127.0.0.1:8765`.

## Safety / compliance notes

- Do not bypass Cloudflare, CAPTCHAs, private APIs, or security controls.
- Keep volume low.
- Use your own account only.
- Do not collect private user information you are not allowed to store.
- Do not commit `auth/*_state.json` or `.env`.
