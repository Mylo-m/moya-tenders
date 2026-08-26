# MOYA — Core Memory (always-on context)

> This is the "soul.md" for the Moya build: the few essentials that should
> always be in context. Everything else lives in `.claude/skills/` and is
> loaded on demand (progressive disclosure).

## Identity
- **Moya** = MY-LO's autonomous agentic tender desk for African markets.
- **Owner**: Kamil Meer Motala (MYLO / My Life Online).
- **Goal**: help African SMEs find + win tenders via an agent that scrapes,
  shreds (Gemini), and auto-drafts bid packages — no human in the loop.

## Non-negotiable rules
1. **Never deploy live without explicit user confirm** (FTP mylo.co.za OR Cloud
   Run). The user has stated this twice. Reversible + backup-first when allowed.
2. **Never fabricate tender data.** Only real, sourced tenders. Empty > fake.
3. **Small reviewable diffs. Plan before edits. Validate after every change**
   (run `smoke_tests.py` — pre-commit hook enforces this).

## Current state (2026-08-26)
- Agentic core: DONE (operator runs across all 15 countries).
- Live dashboard: DONE + visible (all countries show; UG/MW/SC seeded real).
- Cloud Run: NOT deployed (no GCP key/billing/gcloud).
- Gemini key: pending in `.env`.
- EG/MZ/BW: empty (no verified feed).
- Hackathon submit: 2026-08-31 17:00 PT. Bonuses: blog+social done; Gemma/Veo/Lyria pending.
- Completion: ~60% demo-ready, ~40% real-tool-ready.

## Where the living files are
- Skills (on-demand): `.claude/skills/{moya-scrape,deploy,smoke,populate-country}/`
- Onboarding: `CLAUDE.md`
- Vault (human + agent browsable): `vault/`
