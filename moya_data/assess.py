"""Moya — Unified Tender Assessment Orchestrator.

Chains the three agents into one flow a user (or the dashboard) calls:

  1. ELIGIBILITY  — can this person/company win the tender alone?
  2. MATCHMAKER   — if not (or always), assemble a winning consortium from the
                    talent graph.
  3. VERNACULAR    — translate the plain-language summary + the consortium brief
                    into the user's local language.

One call -> a complete, plain-language, localized "here is your path to this
tender" answer. This is the full agentic tender desk in a single endpoint.

All three sub-agents use live Gemini 3.5 Flash; each degrades gracefully if
Gemini is quota-limited so the orchestrator never hard-fails.
"""
from __future__ import annotations

import os
from typing import Optional

from eligibility import evaluate_eligibility
from matchmaker import build_consortium
from vernacular import localize_tender
from talent_db import get_profile


def assess_tender(
    tender: dict,
    profile_id: Optional[int] = None,
    lang: Optional[str] = None,
    model: Optional[str] = None,
) -> dict:
    """Run the full assessment. `lang` like 'zu' localizes the output."""
    result: dict = {"ok": True, "tender_id": tender.get("id")}

    # 1) Eligibility (needs a profile; skip gracefully if none given)
    if profile_id:
        try:
            result["eligibility"] = evaluate_eligibility(tender, profile_id=profile_id, model=model)
        except Exception as e:
            result["eligibility"] = {"ok": False, "error": str(e)}
    else:
        result["eligibility"] = None

    # 2) Matchmaker — always try to build a consortium (the hero feature)
    try:
        result["consortium"] = build_consortium(tender, model=model)
    except Exception as e:
        result["consortium"] = {"ok": False, "error": str(e)}

    # 3) Vernacular — localize the plain summary if a language is requested
    if lang:
        try:
            result["localized"] = localize_tender(tender, langs=[lang], model=model)
        except Exception as e:
            result["localized"] = {"ok": False, "error": str(e)}
    else:
        result["localized"] = None

    # Headline decision for the UI
    elig = result.get("eligibility") or {}
    cons = result.get("consortium") or {}
    if elig.get("verdict") == "ELIGIBLE":
        result["headline"] = "You can likely win this tender alone."
    elif elig.get("verdict") in ("ELIGIBLE_IF", "NOT_ELIGIBLE"):
        result["headline"] = (
            "You may not qualify alone — here is a winning consortium that can."
            if cons.get("ok") else
            "You may not qualify alone; consortium build unavailable (Gemini limited)."
        )
    else:
        result["headline"] = (
            "Here is a suggested consortium for this tender."
            if cons.get("ok") else "Assessment partial (Gemini limited)."
        )
    return result


if __name__ == "__main__":
    import json
    from scraper_sqlite import get_db
    db = get_db()
    t = db.execute("SELECT * FROM tenders WHERE status='open' AND country_code='ZA' ORDER BY id DESC LIMIT 1").fetchone()
    db.close()
    out = assess_tender(dict(t), profile_id=1, lang="zu")
    print(json.dumps(out, indent=2, ensure_ascii=False)[:1800])
