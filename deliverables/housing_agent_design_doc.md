# Housing Search Agent Design Document

## Problem, User, Motivation, and Scope

This project implements a provider-aware housing search agent for students looking for housing near major university hubs. Students may need short-term sublets, long-term apartments, rooms with or without roommates, specific amenities, certain campus distances, and exact move-in or move-out dates. The agent extracts a structured housing intent, asks only useful follow-up questions, chooses which of the three housing-site tools to call, executes only after confirmation, parses external listing data, saves artifacts, and presents ranking metrics and narrowing tools.

The implementation intentionally does not bypass Cloudflare, CAPTCHAs, private APIs, login protections, or rate limits. The LLM handles language understanding, readiness, and cautious ranking text. Deterministic code owns provider routing, URL construction, browser execution, persistence, and command handling.

## End-to-End Workflow

1. User enters a housing request.
2. The Mistral JSON client updates a merged `HousingSearchIntent`.
3. The readiness evaluator checks whether enough information exists and asks preference questions when the correct housing-site tool is unclear.
4. The query planner retrieves provider capabilities and ranks Ohana, RentalSource, and AffordableHousing.com.
5. The agent asks for explicit confirmation before running tools.
6. The deterministic provider router calls the selected provider scraper.
7. Scrapers collect, parse, clean, and normalize visible external listing data.
8. Results are saved to `data/raw`, `data/processed`, and `data/debug`.
9. Listing evaluator and ranker compute decision metrics, recommendations, verification needs, and exclusions.
10. Result commands let the user compare, explain, sort, filter, or show a map.

## Data Incorporation

- Ohana: browser-based search for supported city URLs, with optional saved login session. Known neighborhoods map to Boston, New York, or San Francisco, but URL search uses only the supported city.
- RentalSource: public URL search with source-side filters for city, price, beds, baths, property type, pets, photos, sort, and page, plus optional detail enrichment.
- AffordableHousing.com: SEO path search using city-state slugs such as `boston-ma`, with filters for under-price, bedrooms, property type, Section 8, pet-friendly, accessibility, utilities, washer/dryer, and income-restricted housing.

All providers write raw JSONL, processed CSV, and debug artifacts so the system can reliably reuse and inspect the data it collected.

## Memory and Retrieval

The system uses structured memory rather than a vector database. The interactive agent stores transcript, current intent, readiness, query plan, pending confirmation, execution result, listing ranking, deterministic listing decisions, visible result set, and debug payloads. Retrieval happens over this structured state and the provider capability matrix.

## Three Main Scraping Tools

The three main tools are the three site scrapers. The agent's main job is determining which of these tools to call.

1. Ohana scraper: used for students looking for short-term sublets, private/shared rooms, furnished rooms, solo housing, or student-oriented stays.
2. RentalSource scraper: used for students seeking regular apartments, houses, full rentals, longer-term leases, or housing with multiple roommates.
3. AffordableHousing.com scraper: used for students with extenuating housing conditions such as voucher, Section 8, income-restricted, accessibility, utilities-included, or similar affordability-oriented constraints.

Supporting components make these tools safe: the LLM extracts preferences and readiness, while deterministic planning code chooses the tool and the router executes only allowlisted providers after user confirmation.

## Provider Decision Logic

- Single user, private/shared room, student/sublet, campus, summer, or semester searches route toward Ohana.
- Full rentals with multiple roommates and general apartment/house searches route toward RentalSource.
- Affordable, Section 8, voucher, income-restricted, accessibility, utilities-included, or washer/dryer conditions route toward AffordableHousing.com.

The planner also scores filters: verified source filters add the most value, post-filters add some value, unknown filters reduce confidence, unsupported filters penalize the provider, implemented providers receive a boost, and login requirements add a small cost.

## Guardrails

- Neighborhoods are not tracked as initial search filters.
- Neighborhood-only input asks for the larger city.
- The LLM cannot execute tools, build provider URLs, or set browser flags.
- Execution requires user confirmation.
- Providers are allowlisted.
- Ohana refuses unsupported location URLs.
- RentalSource detail enrichment rejects untrusted detail URLs.
- AffordableHousing uses canonical city-state slugs.
- Provider failures are returned as typed results rather than crashing.
- Missing listing facts remain missing and reduce confidence.

## Evaluation

Current local run: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v` passed 108 tests with 4 live tests skipped behind explicit environment flags.

Test coverage includes intent extraction, readiness, neighborhood handling, provider capabilities, query planning, provider routing, chat CLI, interactive state transitions, URL builders, parsing/storage, scraper helper behavior, failure handling, result metrics, ranking parsing, and golden transcripts. Live LLM and live scrape tests are opt-in with `RUN_LIVE_LLM_TESTS=1` / `RUN_LIVE_SCRAPE_TESTS=1`.

## Example Transcripts

### Successful case

User: I need a furnished private room in Boston under 1800 for the summer.
Agent: I would start with Ohana because it is the best fit for single-room and student/sublet searches. Want me to run it?
User: yes
Agent: Search execution finished, with decision metrics and saved artifacts.

### Ambiguous case

User: I need housing in New York.
Agent: Is this just for you/private room/student/sublet, a regular rental/full rental with multiple roommates, or affordable/voucher/accessibility housing?
User: My roommates and I need a 3 bed apartment under 5000.
Agent: I would start with RentalSource because it is the best fit for multiple-roommate full rentals. Want me to run it?

### Failure-handling / safety case

User: Search Cambridge.
Agent: What larger city or metro area should I search for that area?
User: Boston, and I need a private room.
Agent: I would start with Ohana. The search URL uses Boston, not Cambridge. Want me to run it?

## Limitations

The system uses structured session memory, not vector retrieval. Live scraping can break when provider DOMs or defenses change. Some filters, especially dates and amenities on certain providers, are explicitly unverified. The map is a relative coordinate visualization rather than full geocoding or transit routing.
