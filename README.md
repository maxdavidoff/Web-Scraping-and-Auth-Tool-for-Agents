# Ohana Search Agent — Simple Playwright Starter

This is a small, test-first browser automation project for logging into Ohana with your own account, running a search, extracting visible listing-card information, and saving results to files. It also includes a lightweight LLM planner that can turn a student's natural-language housing request into an Ohana search, run the scraper, and summarize the results.

It intentionally does **not** bypass Cloudflare, CAPTCHAs, login protections, private APIs, or rate limits. Use it only with an account you are allowed to use and only at low, human-like volume.

## What it does

1. Opens Ohana in a real Chromium browser.
2. Lets you log in manually once.
3. Saves the browser session to `auth/ohana_state.json`.
4. Reuses that session to open a search page.
5. Either:
   - lets you perform the search manually, or
   - tries to fill a search box using editable selectors.
6. Extracts likely listing cards from the visible search results.
7. Saves:
   - raw JSONL to `data/raw/`
   - readable CSV to `data/processed/`
   - screenshot + HTML debug files to `data/debug/`

## Folder structure

```text
ohana_search_agent/
  auth/
    ohana_state.json              # created after login; gitignored

  data/
    raw/                          # JSONL results
    processed/                    # CSV results
    debug/                        # screenshot + HTML snapshots

  src/ohana_agent/
    browser.py                    # Playwright browser/session helpers
    config.py                     # settings and paths
    extractor.py                  # DOM extraction logic
    housing_agent.py              # LLM planner + student-facing result summary
    parsing.py                    # field normalization / regex guesses
    search_runner.py              # importable Ohana scraping tool
    storage.py                    # JSONL + CSV writers

  save_ohana_login.py             # Step 1: save login session
  run_ohana_search.py             # Step 2: run/extract search
  run_housing_agent.py            # LLM student-housing agent
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

For the LLM student-housing agent, set:

```bash
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
```

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

## Step 4 — Run the student housing agent

After your Ohana login session is saved, start the intake flow:

```bash
python run_housing_agent.py --max-listings 10 --fetch-listing-api
```

The agent will:

1. Ask what the student is looking for.
2. Ask follow-up questions to refine the search.
3. Clarify whether this is a solo room/sublet search or a longer lease with friends.
4. Stop asking questions when the student says something like "that's all", "done", or "search now".
5. Build the Ohana filtered search URL and scrape automatically.
6. Save CSV/JSONL outputs and produce a short student-facing summary.

You can seed the intake with an initial request:

```bash
python run_housing_agent.py \
  "I'm a Northeastern student looking for a furnished private room in Boston under $1800" \
  --max-listings 10
```

To skip follow-up questions and use the older one-shot behavior:

```bash
python run_housing_agent.py \
  "furnished private room near Northeastern under $1800 from May 1 to August 31, 2026" \
  --one-shot
```

If you want to watch the browser while debugging:

```bash
python run_housing_agent.py "private room near NYU under $2200 for fall 2026" --headed
```

The reusable integration point for a larger system is:

```python
from src.ohana_agent.housing_agent import run_student_housing_agent

result = run_student_housing_agent(
    "Private room near Harvard under $1700 from June 1 to August 31, 2026",
    max_listings=10,
    fetch_listing_api=True,
)

print(result.plan)
print(result.search.records)
print(result.summary)
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

Outputs appear in:

```text
data/raw/affordablehousing_results_YYYYMMDD_HHMMSS.jsonl
data/processed/affordablehousing_results_YYYYMMDD_HHMMSS.csv
data/debug/affordablehousing_search_page.png
data/debug/affordablehousing_search_page.html
```

If extraction breaks, inspect `data/debug/affordablehousing_search_page.html` and update `selectors.affordablehousing.json`.

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
