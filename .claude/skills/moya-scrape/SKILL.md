---
name: moya-scrape
description: "Run or extend Moya's multi-country tender scraper (OCDS + official portals). Use when adding a country, fixing a scraper, or refreshing the tender store. Covers COUNTRY_REGIONS, idempotent source_key, and the per-country playbook pattern."
version: 1.0.0
author: MY-LO
license: MIT
---
# Moya Scrape Skill

## When to use
- Refreshing the tender store (`python3 moya_data/scraper_sqlite.py`).
- Adding a new country to `COUNTRY_REGIONS` + a scraper function.
- Debugging a portal that returns 0 rows or errors.

## Core mental model
- One SQLite store (`moya.db`), many country scrapers. `COUNTRY_REGIONS` in
  `scraper_sqlite.py` is the single source of truth for which countries exist.
- **Idempotency**: every row has a stable `source_key` (sha256 of
  `country_code:source:url`). Use `INSERT OR IGNORE` — never blind INSERT.
- Each country has its own `scrape_<cc>_*` function + a `log_scrape()` call so
  failures are audited in `scrape_log` and never block the other countries.

## Adding a country (playbook)
1. Add the ISO-2 code + region to `COUNTRY_REGIONS`.
2. Add a scraper function following the existing OCDS/OCP pattern
   (`_scrape_ocp_best_effort`) OR a portal HTML scraper.
3. Wire it into `run()` with try/except + `log_scrape(..., status=...)`.
4. Add the country to the dashboard dropdown (`dashboard.php`) + the
   `populate_empty_countries.py` list if seeding real tenders.
5. Run `smoke_tests.py` — confirm the new country appears.

## Common pitfalls
- OCP publisher IDs (`*_OCP_PUB`) default to `None` → that country self-skips.
  Find the real ID at data.open-contracting.org before claiming it works.
- Don't fabricate tenders for a country with no verified feed. Leave it empty;
  the dashboard shows an honest "no match" state.
- JS-gated portals (e.g. Botswana PPADB, Egypt aggregators) need a real fetch
  strategy — don't assume `requests.get` works.

## References
- `moya_data/scraper_sqlite.py` — all scraper logic.
- `moya_data/populate_empty_countries.py` — verified real-seed pattern (UG/MW/SC).
