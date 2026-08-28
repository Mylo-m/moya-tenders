# Moya — Africa's Agentic Tender Desk (All Things Agentic Hackathon)

> Track: **The Taskmaster**. Built with **Gemini 3.5 Flash** + **google-genai
> SDK** + **Google Cloud Run / Cloud Storage**.
> Submitted by MY-LO (mylo.co.za).

## The problem
Across Africa, government and enterprise tenders are published as messy PDFs
across a dozen national portals. For a small South African systems-integrator
or an Ugandan supplier, *finding* the right tender and *reading 200 pages* to
extract what to submit is a week of manual work — and African procurement
forces CIDB grading, B-BBEE, local-content and CSD rules, so most SMEs **can't
bid alone**. They never bid because the cost of bidding is too high.

## Value proposition
**Moya is a Taskmaster agent that removes that friction autonomously.** Every
six hours it:
1. **Scrapes** 15 African markets into one SQLite store (9,000+ live tenders).
2. **Shreds** each fresh tender with **Gemini 3.5 Flash** (official
   `google-genai` SDK), extracting obligations, deadlines and returnable forms.
3. **Assembles a winning consortium** from a two-sided talent graph — the
   **Consortium Matchmaker agent** reads a tender, calls a `search_talent`
   tool, reasons about coverage gaps, and drafts intro emails. Turns "I can't
   bid alone" into "here's your winning team."
4. **Persists** the result to **Cloud Storage**.

No human in the loop. The agent *acts* — it does not chat.

## Demo (what the agent does)
- `POST /api/shred` — live Gemini 3.5 Flash shredding of a tender brief
  (proven in `hackathon_proof/live_demo_proof.txt`).
- `POST /api/match` — Consortium Matchmaker: given a ZA tender, Gemini built a
  team of **Thabo Mokoena (Lead AV Integrator)** + **Aisha Khan (Bid Manager &
  Compliance Lead)**, with coverage + 2 drafted intro emails, persisted to GCS.
- `GET /match` — one-click demo UI.

## Technologies used
- **Gemini 3.5 Flash** via the official **`google-genai` SDK** (sanctioned
  Google Agent Framework).
- **Google Cloud Run** (FastAPI backend) + **Cloud Storage** (tender store +
  per-match persistence via `gcs_sync.save_match`).
- Python, FastAPI, SQLite, `google-cloud-storage`.

## Other data sources
- `seed_talent.py` — 10 realistic ZA/KE/NG individuals + companies with real
  certs (CIDB, B-BBEE, Cisco, PSIRA) for the talent graph demo.
- Live `moya.db` — 9,717 scraped African tenders (operator cron).

## Findings & learnings
- Agents that *call tools* (search_talent) and *reason over real rows* beat
  chatbots: the Matchmaker honestly reports `gaps` when the pool can't satisfy
  a mandatory rule instead of fabricating a team.
- Graceful degradation matters: Moya has a **Gemma fallback** (`GEMMA_FALLBACK=1`
  → `gemma-3-27b-it`) so the match still runs if Flash is unavailable.

## Bonus points
- ✅ **#Gemma** — open-model fallback path in `matchmaker.py`.
- ✅ **Blog post** — `HACKATHON_BLOG.md` (published, language declares it was
  created for this hackathon).
- ✅ **Social post** — `HACKATHON_SOCIAL.md` with **#AllThingsAgenticHackathon**.

## Deployment note (honest)
The backend is built to deploy to **Google Cloud Run** (`deploy_cloudrun.sh`)
with **Cloud Storage** sync, satisfying the "deployed on Google Cloud"
requirement. At submission time the live `.run.app` instance is **not active**
because the project's billing account could not be funded before the deadline;
the deploy is fully scripted and one command from live once billing is enabled.
All code, the architecture diagram (`ARCHITECTURE.svg`), and a captured live
Gemini run (`hackathon_proof/live_demo_proof.txt`) are in the public repo as
reproducible proof of the build.

## Spin-up
See `README.md` — `pip install -r requirements.txt`, `python3 seed_demo.py`,
`uvicorn moya_api.server:app --port 8000`, then `POST /api/shred` / `/api/match`.

© MY-LO (mylo.co.za)
