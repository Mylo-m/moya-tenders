# Hackathon Plan — All Things Agentic (Gemini + Google Cloud)

**Submit:** 2026-08-31 17:00 PT
**Repo:** github.com/Mylo-m/moya-tenders

## Must-haves (judging requirements)
- [x] Agentic core (scrape → Gemini shred → auto-draft → audit) — DONE
- [ ] **Cloud Run deploy** — BLOCKER. Needs GCP project + billing + `gcloud` + key.
- [x] Gemini client wired — key pending in `.env`
- [x] Multi-country scraper, 10k+ tenders
- [ ] Demo video + README live-URL proof

## Bonuses (+0.2 each, max +0.6) — 1/5 done
- [x] Blog post (`HACKATHON_BLOG.md`)
- [x] #AllThingsAgentic social (`HACKATHON_SOCIAL.md`)
- [ ] Gemma model swap
- [ ] Veo (video gen)
- [ ] Lyria (music gen)

## Outstanding decisions
- EG/MZ/BW: build real scrapers or leave empty?
- WITS proposal: which file is "the" deliverable (MYLO_Wits vs wits-alloy-db)?
- Deploy timing: when to flip Cloud Run live?
