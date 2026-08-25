# MY-LO · Moya — Africa's Agentic Tender Desk

**Built for the [All Things Agentic Hackathon](https://allthingsagentichackathon.devpost.com/) (Gemini + Google Cloud).**

Moya is an autonomous agentic system that monitors government & enterprise
tenders across **11+ African markets**, then uses **Gemini** to shred
200-page procurement PDFs, verify bid compliance, and auto-draft submission
packages — turning a week of manual bid work into minutes.

## What it does (agentic, not chatbot)

- **Scrape** — backgrounds multi-country tender portals (ZA, KE, NG, ZM, TZ,
  GH, ZW, MA, RW, MU, ET, …) on a 6-hour cron, normalising them into one SQLite
  store (9,000+ live tenders).
- **Shred** — Gemini parses tender documents, extracts obligations, deadlines,
  and returnable forms.
- **Comply** — `compliance.py` evaluates bid-readiness against country-specific
  procurement rules (SA SBD / Kenya PPADA).
- **Draft** — `doc_engine.py` assembles a render-ready bid data-package
  (SBD1/4/5/8, pricing, B-BBEE, CIDB).
- **Deliver** — dashboard + WhatsApp field alerts push matches to SMEs.

## Architecture (30% judging — discipline)

```
[ Tender Portals ]  ──►  [ scraper_sqlite.py ]  ──►  [ moya.db (SQLite) ]
                                                        │
                                                    [ moya_api (FastAPI) ]
                                                        │  Gemini (bid shred / draft)
                                                        ▼
                              [ dashboard.php / moya_ai.php ]  ──►  [ SME / WhatsApp ]
```

- **State**: SQLite (source of truth), idempotent `source_key` upserts.
- **Credentials**: loaded from env at runtime; never in repo (see `.gitignore`).
- **Failure handling**: per-source try/except + `scrape_log` audit; one dead
  portal never blocks the run.
- **Cloud**: deployable to Cloud Run (FastAPI) + Cloud Storage (DB sync).

## Run locally

```bash
pip install -r requirements.txt
python3 moya_data/scraper_sqlite.py          # refresh tenders
uvicorn moya_api.main:app --port 8000         # API + Gemini shredder
```

## Layout

| Path | Role |
|------|------|
| `moya_data/scraper_sqlite.py` | Multi-country tender scraper (OCDS + portals) |
| `moya_data/compliance.py` | Bid-readiness evaluator |
| `moya_data/doc_engine.py` | Bid document/data-package builder (ZA, KE) |
| `moya_data/whatsapp_digest.py` | Field-alert digest |
| `moya_api/main.py` | FastAPI: proposal-gen, counters, health |
| `moya_ai.php` / `moya_ai_parser.php` | Gemini bid-shredder (web) |
| `dashboard.php` | Command-center dashboard |
| `compliance*.php` | Compliance UI |
| `signup_plan.php` / `payfast_*.php` | Founding-member access |

## Tech

`gemini-api` · `google-cloud-platform` · `python` · `fastapi` · `php` ·
`sqlite` · `reportlab` · `tailwindcss` · `javascript`

© MY-LO (mylo.co.za)
