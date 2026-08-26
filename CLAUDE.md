# CLAUDE.md — Moya (All Things Agentic Hackathon build)

> Onboarding doc for any coding agent. What the project does, where things live,
> how work gets done. Keep lean — essentials only.

## What this is
MY-LO Moya: an **autonomous agentic tender desk** for African markets. It scrapes
government/enterprise tenders across 15 countries into one SQLite store, uses
**Gemini 3.5 Flash** to shred tender docs + auto-draft bid packages, and serves
them via a dashboard + FastAPI Cloud Run backend. Built for the All Things
Agentic Hackathon (Gemini API + Google Cloud). Submit by 2026-08-31 17:00 PT.

## Tech stack
- Python 3.11 · FastAPI (Cloud Run) · SQLite (source of truth) · PHP (dashboard)
- `google-genai` SDK for Gemini · `google-cloud-storage` for cloud DB sync
- `reportlab` for bid-package PDFs · `ftplib` for live FTP deploys

## Where things live
- `moya_data/scraper_sqlite.py` — multi-country tender scraper (OCDS + portals). `COUNTRY_REGIONS` defines the 15 markets.
- `moya_data/operator.py` — **the agentic core**: scrape → Gemini shred → auto-draft bid package → audit. Runs across ALL countries (no ZA/KE hardcode).
- `moya_data/gemini_client.py` — Gemini client (SDK + REST fallback). Reads `GEMINI_API_KEY` from env (auto-loads `.env`).
- `moya_data/compliance.py` / `doc_engine.py` — bid-readiness eval + package builder.
- `moya_data/auto_close_expired.py` — flips past-closing tenders to `closed`.
- `moya_data/freshness_monitor.py` — per-country staleness alert.
- `moya_data/smoke_tests.py` — **run this after ANY code change** (`python3 moya_data/smoke_tests.py`, set `MOYA_DB_PATH` to a populated DB).
- `moya_api/server.py` — FastAPI: `/api/tenders`, `/api/stats`, `/api/shred` (live Gemini). Deploy target = Cloud Run.
- `dashboard.php` (live at `public_html/moya_data/`) — customer-facing command center. Reads `moya.db` via `moya.php`.
- `deploy_cloudrun.sh` — one-command Cloud Run deploy (needs GCP project + billing + `gcloud`).

## How work gets done
1. **Plan before editing** — lay out files/risk, get confirmation for structural changes.
2. **Small steps** — tight, reviewable diffs. Don't batch 15-file changes.
3. **Validate after every change** — run `smoke_tests.py`. Green before moving on.
4. **Reversible** — git commit; backups before live FTP overwrites (`*.bak_*`).
5. **No live deploy without explicit user confirm** — dashboard/DB changes stay local until the user says go.
6. **Never fabricate tender data** — only real, sourced tenders. Missing-feed countries (EG/MZ/BW) stay empty, not faked.

## Key conventions
- `country_code` uses ISO-2 (ZA, KE, NG, ZM, GH, TZ, ZW, MA, MU, ET, RW, UG, MW, SC, EG, MZ, BW).
- `source_key` = stable hash → idempotent upserts (never duplicate rows).
- Operator degrades gracefully if Gemini key missing (drafts from title+sector).
- Live DB is at `public_html/moya.db` AND `public_html/moya_data/moya.db` (TWO copies — know which is source of truth before writing).

## Dev commands
- Scrape: `python3 moya_data/scraper_sqlite.py`
- Operator (dry-run): `python3 -c "from moya_data import operator as o; o.run_operator(dry_run=True)"`
- Smoke: `MOYA_DB_PATH=<populated.db> python3 moya_data/smoke_tests.py`
- Local API: `uvicorn moya_api.server:app --port 8000`

## Outstanding (as of 2026-08-26)
- Cloud Run NOT deployed (no GCP key/billing/`gcloud`).
- Gemini key pending in `.env`.
- EG/MZ/BW tenders empty (no verified feed).
- Demo video + README live-URL pending deploy.
- Bonuses (blog done; Gemma/Veo/Lyria pending).
