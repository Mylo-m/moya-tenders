# Skills Index — Moya Agentic Skills

Load on demand (progressive disclosure). Metadata here; full playbook in each
`.claude/skills/<name>/SKILL.md`.

| Skill | When to use |
|---|---|
| `moya-scrape` | Add/debug a country scraper; understand COUNTRY_REGIONS + idempotent source_key |
| `moya-deploy` | Any live change (FTP or Cloud Run); enforces backup-first + no-deploy-without-confirm |
| `moya-smoke` | Self-validation loop — run after every code change (pre-commit hook uses this) |
| `moya-populate-country` | Seed a country's real tenders idempotently; never fabricate |

## Cross-session memory
- `MOYA_MEMORY.md` — core always-on context (rules, state, links).
- `CLAUDE.md` — onboarding for any coding agent.
- `vault/` — human + agent browsable notes (hackathon plan, business context).
