# How MY-LO Moya Turns 10,000 African Tenders into Auto-Drafted Bids with Gemini

*Submitted for the All Things Agentic Hackathon (Gemini API + Google Cloud).*

## The problem

Across Africa, government and enterprise tenders are published in messy PDFs,
spread across a dozen national portals, in a dozen sectors. For a small South
African systems-integrator or an Ugandan supplier, simply *finding* the right
tender — then reading 200 pages to extract what to submit — is a week of
manual work. Most SMEs never bid because the cost of bidding is too high.

## What we built: an agent that acts, not chats

**Moya** is an autonomous tender desk. Every six hours it:

1. **Scrapes** 15 African markets (South Africa, Kenya, Nigeria, Ghana,
   Zambia, Rwanda, Ethiopia, Tanzania, Zimbabwe, Mauritius, Morocco, Uganda,
   Malawi, Seychelles, and more) into one SQLite store — 10,000+ live tenders.
2. **Shreds** each fresh tender with **Gemini 3.5 Flash** (via the official
   `google-genai` SDK), extracting obligations, deadlines and returnable forms.
3. **Compiles** a bid data-package (SBD/PPADA returnables, pricing skeleton,
   compliance checklist) — fully autonomously, no human in the loop.
4. **Alerts** the SME and writes an audit trail of exactly what it did.

If Gemini is unavailable, Moya degrades gracefully: it still drafts a usable
package from the tender's own title and sector, so the agent never blocks on a
missing dependency.

## Why it's "agentic"

Most hackathon demos are chatbots. Moya *runs*. The differentiator is the
**operator loop**: on every scheduled scrape the system takes real action on
the tenders it collected — shredding, drafting, persisting — and emits an audit
log of what it produced. The demo video simply shows the folder of generated
bid packages from the last run.

## The Google Cloud piece

The backend is deployable to **Cloud Run** (FastAPI) with a **Cloud Storage**
sync for the tender store, satisfying the "deployed on Google Cloud"
requirement. The live `/api/shred` endpoint calls Gemini in real time;
`/api/tenders` and `/api/stats` serve the agent's scraped market.

## What's next

Real SME alerting (Telegram/email), a tender-match engine that scores tenders
against a supplier's sector, and live deployment to a `*.run.app` URL.

---

*MY-LO (mylo.co.za) — agentic procurement intelligence for African SMEs.*
*#AllThingsAgentic #Gemini #GoogleCloud*
