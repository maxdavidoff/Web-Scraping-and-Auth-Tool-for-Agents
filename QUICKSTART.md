# Quickstart

```bash
cd ohana_search_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

Run the automated tests, including live browser scrape coverage:

```bash
python3 -m unittest discover -s tests -v
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
