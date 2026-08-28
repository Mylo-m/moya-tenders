# How MY-LO Moya Turns 10,000 African Tenders into Auto-Drafted Bids — and Assembles the Winning Consortium

*Submitted for the All Things Agentic Hackathon (Gemini API + Google Cloud).*

## The problem

Across Africa, government and enterprise tenders are published in messy PDFs,
spread across a dozen national portals, in a dozen sectors. For a small South
African systems-integrator or an Ugandan supplier, simply *finding* the right
tender — then reading 200 pages to extract what to submit — is a week of
manual work. Most SMEs never bid because the cost of bidding is too high.

And even when they *do* find the right tender, African procurement forces CIDB
grading, B-BBEE, local-content and CSD rules — so a solo pro or small firm
usually **can't bid alone**. That second problem is the one nobody has solved.

## What we built: agents that act, not chat

**Moya** is an autonomous tender desk. Every six hours it:

1. **Scrapes** 15 African markets into one SQLite store — 10,000+ live tenders.
2. **Shreds** each fresh tender with **Gemini 3.5 Flash** (via the official
   `google-genai` SDK), extracting obligations, deadlines and returnable forms.
3. **Compiles** a bid data-package — fully autonomously, no human in the loop.
4. **Alerts** the SME and writes an audit trail of exactly what it did.

If Gemini is unavailable, Moya degrades gracefully: it still drafts a usable
package from the tender's own title and sector.

## The hero feature: the Consortium Matchmaker agent

This is what makes Moya genuinely *agentic* — not a chatbot that summarises, but
an agent that **takes action on a real business problem**.

African tenders demand certs and capacity a solo bidder doesn't have. So Moya
keeps a two-sided **talent graph** (verified local individuals + companies with
real CIDB/B-BBEE/Cisco/PSIRA certs). When you point the Matchmaker at a tender,
it:

1. reads the tender's required capabilities,
2. **calls a tool** (`search_talent`) against the talent graph,
3. **reasons about coverage gaps** with Gemini 3.5 Flash,
4. **assembles the smallest complementary team** that satisfies every mandatory
   cert / location / language rule,
5. **drafts one intro email per member**, and
6. **persists the consortium JSON to Cloud Storage**.

The agent only ever reasons over *real rows* in the talent graph — it never
invents people. And because it's honest, when the pool can't satisfy a mandatory
rule (e.g. "no CISA-certified auditor available in Limpopo"), it says so under
`gaps` instead of faking a team. That's the difference between a demo and a tool
you'd trust with a R5M bid.

Live endpoints (on Cloud Run):
- `POST /api/match` — `{tender_id: 65507}` → Gemini-built consortium, saved to GCS
- `GET /match` — a one-click demo UI: paste a tender, watch the agent build the team
- `POST /api/shred` — real-time Gemini tender shredding
- `GET /api/tenders`, `GET /api/stats` — the agent's scraped market

## The Google Cloud piece

The backend is deployed to **Cloud Run** (FastAPI) with a **Cloud Storage** sync
for the tender store, and the Matchmaker writes its output to Cloud Storage too —
satisfying the "deployed on Google Cloud" requirement. The live `/api/shred` and
`/api/match` endpoints call Gemini 3.5 Flash in real time.

## Why it's "agentic" (and how we grab the bonuses)

- **Gemini 3.5 Flash** is the agent's brain — live, every call.
- **Gemma fallback path**: `matchmaker.py` can route to `gemma-3-27b-it` via
  `GEMMA_FALLBACK=1`, so the match still runs on the open model if Flash is down
  (the #Gemma bonus, with no extra infra).
- **Cloud Storage** is the real data store (requirement #3).
- We post the build to #AllThingsAgenticHackathon and publish this blog (the social +
  blog bonuses).

## What's next

Real SME alerting (Telegram/email), a tender-match engine that scores tenders
against a supplier's sector, and the two-sided talent graph going live for
seekers across ZA/KE/NG.

---

*MY-LO (mylo.co.za) — agentic procurement intelligence for African SMEs.*
*#AllThingsAgenticHackathon #Gemini #GoogleCloud*
