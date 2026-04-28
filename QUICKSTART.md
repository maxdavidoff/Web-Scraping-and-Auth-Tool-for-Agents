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

```bash
python3 -m unittest discover -s tests -v
```

Run only the live scrape tests locally:

```bash
python3 run_live_scrape_tests.py --install-chromium
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

Run the LLM student-housing agent:

```bash
export OPENAI_API_KEY="..."
python run_housing_agent.py --max-listings 10
```

Or seed the intake with an initial request:

```bash
python run_housing_agent.py "furnished private room near Northeastern under $1800" --max-listings 10
```

AffordableHousing.com:

```bash
python save_affordablehousing_login.py --start-url "https://www.affordablehousing.com/"
python run_affordablehousing_search.py --search-url "https://www.affordablehousing.com/boston-ma/" --manual-search --max-listings 20 --keep-open
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
