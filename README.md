# Housing Search Agent — Provider-Aware Browser Tools

This is a small, test-first housing search project for logging into housing providers with your own account when needed, running searches, extracting visible listing-card information, and saving results to files. It also includes an LLM-assisted housing chat loop, deterministic provider capability/query planning, explicit execution confirmation, and post-result listing fit ranking.

It intentionally does **not** bypass Cloudflare, CAPTCHAs, login protections, private APIs, or rate limits. Use it only with an account you are allowed to use and only at low, human-like volume.

Supported search markets are currently Boston, MA; New York, NY; Washington, DC; and Philadelphia, PA. Known neighborhoods inside those markets, such as University City for Philadelphia, are mapped back to the supported city search.

## What it does

1. Extracts or updates a provider-neutral `HousingSearchIntent` from user language.
2. Evaluates search readiness: what is required, what is flexible, and whether a follow-up is useful.
3. Builds a deterministic provider-aware query plan for:
   - Ohana
   - RentalSource
   - AffordableHousing.com
4. Shows the user which provider should run first and why.
5. Executes only after explicit confirmation.
6. Routes execution through the deterministic provider router, not through the LLM.
7. Ranks returned listings against the user intent without inventing missing facts.
8. Saves scraper outputs:
   - raw JSONL to `data/raw/`
   - readable CSV to `data/processed/`
   - screenshot + HTML debug files to `data/debug/`

The LLM is used for language understanding, search readiness, and result-fit explanation. Deterministic code owns provider ranking, URL/query construction, confirmation state, and scraper execution.

## Folder structure

```text
ohana_search_agent/
  auth/
    ohana_state.json              # created after login; gitignored

  data/
    raw/                          # JSONL results
    processed/                    # CSV results
    debug/                        # screenshot + HTML snapshots

  src/housing_agent/
    intent_extractor.py           # Mistral-backed provider-neutral intent extraction
    readiness_evaluator.py        # Mistral-backed search readiness/follow-up policy
    listing_ranker.py             # Mistral-backed listing fit ranking after execution
    llm_client.py                 # small stdlib Mistral chat-completion client
    provider_capabilities.py      # provider capability matrix
    query_planner.py              # deterministic query planning/reporting
    search_app.py                 # one-shot plan/execute app API
    interactive_agent.py          # stateful terminal chat controller
    types.py                      # shared intent/readiness/query/ranking dataclasses

  src/ohana_agent/
    browser.py                    # Playwright browser/session helpers
    config.py                     # settings and paths
    extractor.py                  # DOM extraction logic
    provider_router.py            # deterministic multi-provider router
    parsing.py                    # field normalization / regex guesses
    search_runner.py              # importable Ohana scraping tool
    storage.py                    # JSONL + CSV writers

  run_housing_chat.py             # interactive agent-user loop
  run_housing_search.py           # one-shot plan/execute flow
  run_housing_intent.py           # intent extraction + query plan only
  save_ohana_login.py             # save Ohana login session
  run_ohana_search.py             # run/extract Ohana search
  run_rentalsource_search.py      # run/extract RentalSource search
  run_affordablehousing_search.py # run/extract AffordableHousing search
  selectors.example.json          # editable selectors
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

For provider-neutral intent extraction, set:

```bash
MISTRAL_API_KEY=...
MISTRAL_MODEL=mistral-small-latest
```

No extra Python package is required for the LLM layers; the project uses the small stdlib Mistral client in `src/housing_agent/llm_client.py`.

## Interactive housing chat

Use the chat agent to experience the product flow:

```bash
python run_housing_chat.py --max-listings 5
```

Example:

```text
> i need to find somewhere to stay for a summer program at upenn
```

The agent updates a merged `HousingSearchIntent`, evaluates whether enough information is present, asks at most a small number of useful follow-up questions, then proposes the best provider to run first. Execution requires a clear confirmation such as:

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
  -> LLM updates full merged HousingSearchIntent
  -> LLM evaluates SearchReadiness
  -> deterministic query planner ranks providers and explains filter application
  -> user confirms execution
  -> deterministic provider router runs executable scrapers
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
data/raw/ohana_results_YYYYMMDD_HHMMSS.jsonl
data/processed/ohana_results_YYYYMMDD_HHMMSS.csv
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

If the script cannot find the search box, it will ask you to do the search manually. That means you need to update `selectors.example.json`.

Ohana only writes exact coordinates when `--fetch-listing-api` is enabled and a real `/listing/...` detail URL is available. Each output record includes `coordinates_status` and `coordinates_source` so missing coordinates are explicit instead of silent.

## Query planning layer

The old direct LLM-to-scraper bridge has been removed. The current reusable integration point is layered: extract a provider-neutral structured intent, inspect provider capability/query quality, then call the router explicitly.

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
python run_housing_intent.py "furnished private room in Boston under $1800 for June 2026"
```

The CLI prints the extracted `HousingSearchIntent` and the provider query plan.

For the product-facing search flow, use `run_housing_search.py`. By default it only plans the search and prints the extracted intent, ranked providers, query quality, source-applied filters, unsupported/unverified filters, and execution warnings:

```bash
python run_housing_search.py "I need a furnished private room in Boston under 1800 for the summer"
```

For a back-and-forth terminal experience, use the interactive chat agent:

```bash
python run_housing_chat.py --max-listings 5
```

The chat agent maintains intent across turns, asks follow-up questions when the readiness layer says the search would otherwise be weak, proposes the best provider to search first, and only executes after the user confirms with a reply like `yes`.

Scraping is opt-in:

```bash
python run_housing_search.py "I need a furnished private room in Boston under 1800 for the summer" --execute --max-listings 5
```

The execution path filters out any provider that is not wired to an executable scraper.

Live Mistral tests are opt-in:

```bash
RUN_LIVE_LLM_TESTS=1 MISTRAL_API_KEY=... python3 -m unittest tests.test_intent_extractor -v
```

or:

```bash
python3 run_live_llm_tests.py
```

Live browser scrape tests are opt-in:

```bash
RUN_LIVE_SCRAPE_TESTS=1 python3 -m unittest discover -s tests -v
```

## Updating selectors

Open:

```text
data/debug/search_page.html
```

Find the listing card HTML and update `selectors.example.json`, especially:

```json
"result_card_selectors": [
  "[data-testid*='listing' i]",
  "[class*='listing' i]",
  "[class*='card' i]",
  "article"
]
```

The extraction logic is intentionally heuristic at first. It tries to identify likely cards, then guesses fields like title, price, bedrooms, dates, URL, and image URLs.

For a more accurate second version, inspect the debug HTML and replace the generic selectors with exact Ohana selectors.

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

If the screenshot shows results but CSV is empty, update `result_card_selectors` in `selectors.example.json`.

### Login expired

Run:

```bash
python save_ohana_login.py
```

and log in again.

## Recommended testing workflow

1. Run `save_ohana_login.py`.
2. Run `run_ohana_search.py --manual-search --keep-open`.
3. Check the CSV.
4. Check `data/debug/search_page.html` if extraction is wrong.
5. Tighten selectors.
6. Only then try automated search.

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

For a narrower local readiness check that runs only the live scrape tests:

```bash
python3 run_live_scrape_tests.py --install-chromium
```

Use `--all` if you want full unittest discovery with live tests enabled.

## AffordableHousing.com tool

This repo also includes a parallel AffordableHousing.com tool with the same manual-first workflow:

```bash
python save_affordablehousing_login.py --start-url "https://www.affordablehousing.com/"
```

Login is optional for public searches, but this saves a browser session to:

```text
auth/affordablehousing_state.json
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

To enrich extracted cards with exact detail-page address and coordinates when available:

```bash
python run_affordablehousing_search.py \
  --location "Boston, MA" \
  --property-types Apartment \
  --max-listings 10 \
  --fetch-listing-detail
```

Outputs appear in:

```text
data/raw/affordablehousing_results_YYYYMMDD_HHMMSS.jsonl
data/processed/affordablehousing_results_YYYYMMDD_HHMMSS.csv
data/debug/affordablehousing_search_page.png
data/debug/affordablehousing_search_page.html
```

If extraction breaks, inspect `data/debug/affordablehousing_search_page.html` and update `selectors.affordablehousing.json`.

AffordableHousing detail enrichment validates that detail URLs belong to `affordablehousing.com` before fetching them. Coordinate fields are written as `listing_latitude`, `listing_longitude`, `coordinates_status`, and `coordinates_source`.

## RentalSource tool

This repo also includes a parallel RentalSource tool with the same browser/session/result-saving workflow:

```bash
python save_rentalsource_login.py --start-url "https://www.rentalsource.com/"
```

RentalSource listings are public, so saving a login session is optional unless you need account-specific behavior. Run a filtered search like this:

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

The RentalSource script accepts the same manual-search and keep-open workflow:

```bash
python run_rentalsource_search.py \
  --search-url "https://www.rentalsource.com/boston-ma/" \
  --manual-search \
  --max-listings 20 \
  --keep-open
```

To enrich extracted cards with detail-page JSON-LD fields such as exact address, latitude, longitude, beds, baths, and price range:

```bash
python run_rentalsource_search.py \
  --location "Boston, MA" \
  --max-listings 10 \
  --fetch-listing-detail
```

Without detail enrichment, RentalSource records still include `coordinates_status=not_requested`. With enrichment, coordinates come from detail-page JSON-LD when present.

RentalSource outputs appear beside the other outputs:

```text
data/raw/rentalsource_results_YYYYMMDD_HHMMSS.jsonl
data/processed/rentalsource_results_YYYYMMDD_HHMMSS.csv
data/debug/rentalsource_search_page.png
data/debug/rentalsource_search_page.html
```

If extraction breaks, inspect `data/debug/rentalsource_search_page.html` and update `selectors.rentalsource.json`.

## Safety / compliance notes

- Do not bypass Cloudflare, CAPTCHAs, private APIs, or security controls.
- Keep volume low.
- Use your own account only.
- Do not collect private user information you are not allowed to store.
- Do not commit `auth/*_state.json` or `.env`.
