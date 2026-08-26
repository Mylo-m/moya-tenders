---
name: moya-smoke
description: "Run Moya's self-validation loop after any code change. Use this as the automatic gate (Maddy's validation-harness pattern): run build/tests/smoke after every edit so breakage is caught before the customer sees it."
version: 1.0.0
author: MY-LO
license: MIT
---
# Moya Smoke Skill (self-validation loop)

## Why
Per the senior-engineer workflow: wire a validation harness that runs after
every change so the agent catches its own mistakes. For Moya, that harness is
`smoke_tests.py`.

## How to run
```bash
# point at a populated DB (staging DB is often empty; use the live copy)
export MOYA_DB_PATH=/path/to/populated/moya.db
python3 moya_data/smoke_tests.py
```
Exit 0 = all green. Exit 1 = a check failed (reads the printed failures).

## What it checks
- DB reachable + non-empty
- All configured countries present in the store
- Operator spans >2 countries (not just ZA/KE)
- Operator drafts a bid package (offline path, no Gemini needed)
- auto_close_expired + freshness_monitor import & run
- gemini_client reads GEMINI_API_KEY from env

## Gate rule
Run smoke_tests.py after EVERY code change to moya_data/ or moya_api/. Do not
report a task complete until it's green. If a country is legitimately empty
(EG/MZ/BW — no verified feed), that failure is expected, not a bug.

## Wiring as an automatic hook (recommended)
Add a pre-commit / post-edit hook that runs `smoke_tests.py` and blocks on
failure — mirrors Maddy's "after every edit, run build+test, treat failure as
blocker" pattern.
