---
name: moya-populate-country
description: "Seed a country's real tenders into moya.db without fabricating data. Use when a country has 0 tenders and you have a verified official/aggregator source. Encodes the idempotent insert pattern + the no-fake-data rule."
version: 1.0.0
author: MY-LO
license: MIT
---
# Moya Populate-Country Skill

## The one rule
**Never invent tender data.** Only insert tenders sourced from a real, verifiable
portal (official eGP/PPDA/NTB pages, or a real aggregator with live refs +
deadlines). If no verified feed exists for a country, leave it empty — the
dashboard shows an honest "no match" state.

## Verified sources (working as of 2026-08-26)
- UG: egpuganda.go.ug (official PPDA eGP bid notices) — real refs + deadlines.
- MW: malawitenders.com (real latest, MWT ref numbers + deadlines).
- SC: ntb.sc (Seychelles National Tender Board advertised tenders).
- NG/GH/RW/ZM/ET/KE/ZA/TZ/ZW/MA/MU: existing OCDS/portal scrapers.

## No verified feed (leave empty, do NOT fake)
- EG, MZ, BW — JS-gated / loading screens; no open API reachable. Build a real
  OCP/OCDS scraper (see moya-scrape) before claiming coverage.

## Idempotent insert pattern
```python
import sqlite3, hashlib
DB = "moya.db"
def key(src, uid): return hashlib.sha256(f"{src}:{uid}".encode()).hexdigest()[:16]
SQL = """INSERT OR IGNORE INTO tenders
 (source,source_key,title,description,issuing_dept,sector,province,country,
  country_code,region,advert_date,closing_date,status,source_url,created_at)
 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, datetime('now'))"""
db = sqlite3.connect(DB)
db.execute(SQL, (src, key(src,uid), title, "", dept, sector, "",
    country, cc, region, adv, (close+" 23:59:00") if close else "", "open", url))
db.commit()
```
- `source_key` = stable hash → re-running never duplicates.
- `closing_date` empty string means "TBC" (dashboard renders "Closing date TBC").
- `sector` should be one of the known buckets (construction, transport,
  consulting, ict, energy, insurance, retail, ...) so the dashboard filters work.

## After seeding
1. Run `moke_tests.py` with `MOYA_DB_PATH` pointed at the seeded DB.
2. Confirm the country now appears with >0 tenders.
3. If live: deploy via moya-deploy skill (backup-first, user confirm).
