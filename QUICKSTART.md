# Quickstart

```bash
cd ohana_search_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Run the automated tests. Live browser scrape tests are skipped unless you set
`RUN_LIVE_SCRAPE_TESTS=1`:

Supported search markets are Boston, MA; New York, NY; Washington, DC; and Philadelphia, PA. Known neighborhoods inside those markets, such as University City for Philadelphia, are mapped back to the supported city search.

```bash
python3 -m unittest discover -s tests -v
```

Run only the live scrape tests locally:

```bash
python3 run_live_scrape_tests.py --install-chromium
```

Run mocked Mistral intent extraction tests. Live LLM calls are skipped unless
you set `RUN_LIVE_LLM_TESTS=1` and `MISTRAL_API_KEY`:

```bash
python3 -m unittest tests.test_intent_extractor -v
```

Run the live Mistral intent extraction test locally:

```bash
export MISTRAL_API_KEY="..."
python3 run_live_llm_tests.py
```

Save login:

```bash
python save_ohana_login.py --start-url "https://liveohana.ai/"
```

Run first manual extraction test:

```bash
python run_ohana_search.py --search-url "https://liveohana.ai/" --manual-search --max-listings 20 --keep-open
```

Check results:

```text
data/processed/
data/raw/
data/debug/
```

Extract and plan a provider-neutral housing intent without scraping:

```bash
export MISTRAL_API_KEY="..."
python run_housing_intent.py "furnished private room in Boston under $1800 for June 2026"
```

Plan the user-facing search experience without scraping:

```bash
python run_housing_search.py "I need a furnished private room in Boston under 1800 for the summer"
```

Try the interactive chat agent:

```bash
python run_housing_chat.py --max-listings 5
```

Try the local browser UI:

```bash
python run_housing_ui.py --max-listings 5 --fetch-listing-api
```

Then open `http://127.0.0.1:8765`. The UI shows the chat, intent, provider plan, execution state, listing cards, listing images, output files, and scraper screenshots from `data/debug/`.

The chat agent:

1. updates a provider-neutral housing intent from the conversation,
2. evaluates whether the search is ready or needs a useful follow-up,
3. proposes the best provider to run first,
4. asks before executing anything,
5. ranks returned listings against the intent after execution.

Reply `yes` to execute the proposed search, or `no` to keep planning. Use `json` inside the chat to inspect the current intent, readiness object, provider plan, execution state, and ranking output.

Execute only when you explicitly want live scrapers to run:

```bash
python run_housing_search.py "I need a furnished private room in Boston under 1800 for the summer" --execute --max-listings 5
```

No live LLM or browser scrape tests run by default. Use these only when you explicitly want live calls:

```bash
RUN_LIVE_LLM_TESTS=1 MISTRAL_API_KEY="..." python3 -m unittest tests.test_intent_extractor -v
RUN_LIVE_SCRAPE_TESTS=1 python3 -m unittest discover -s tests -v
```

AffordableHousing.com:

```bash
python save_affordablehousing_login.py --start-url "https://www.affordablehousing.com/"
python run_affordablehousing_search.py --search-url "https://www.affordablehousing.com/boston-ma/" --manual-search --max-listings 20 --keep-open
python run_affordablehousing_search.py --location "Boston, MA" --max-listings 10 --fetch-listing-detail
```

RentalSource:

```bash
python save_rentalsource_login.py --start-url "https://www.rentalsource.com/"
python run_rentalsource_search.py --location "Boston, MA" --property-types Apartment --num-bedrooms 1 --num-bathrooms 1 --min-price 1000 --max-price 3000 --sort price --max-listings 20
```

Optional RentalSource detail enrichment:

```bash
python run_rentalsource_search.py --location "Boston, MA" --max-listings 10 --fetch-listing-detail
```

Coordinate fields are explicit in provider outputs. Look for `coordinates_status`, `coordinates_source`, `listing_latitude`, and `listing_longitude`. Ohana needs `--fetch-listing-api` and real listing URLs for coordinates; RentalSource and AffordableHousing use detail-page enrichment.
