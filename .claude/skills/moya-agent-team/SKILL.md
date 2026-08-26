---
name: moya-agent-team
description: "Run Moya build as a team of agents (Ryan Carson pattern): isolated cloud/local sessions per task, parent orchestrator + child workers, daily production watchdog + self-improvement loop. Use when scaling parallel work or automating the operator."
version: 1.0.0
author: MY-LO
license: MIT
---
# Moya Agent-Team Skill

## Principles (from managing teams of AI agents)
- **Isolated sessions**: run per-country scrapers / independent fixes in separate
  processes or git worktrees so work never collides. Don't run one fragile script.
- **Parent + children**: `cron_scrape` is the parent; per-country scrapers are
  children. One manager thread spins up workers.
- **Production watchdog**: a daily digest of what happened (new tenders, operator
  output) with links — `production_watchdog.py` (dry-run default).
- **Self-improvement loop**: grade generated packages on a rubric; flag
  below-threshold for a cheap-model fix pass — `self_improve_loop.py`.
- **Model routing**: premium model (Gemini 3.5 Flash) for the hard shred;
  cheap model (Gemma) for grading/loop. Never burn premium tokens on grading.
- **Keys separate from agents**: prod-write DB keys are NOT auto-loaded. Deploy
  skill enforces explicit confirm + backup.

## Cadence
- Watchdog: every morning, read the digest, make high-stakes calls.
- Self-improve: daily, cheap-model pass, 3 small fixes/day.
