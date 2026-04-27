# Quickstart

```bash
cd ohana_search_agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
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
