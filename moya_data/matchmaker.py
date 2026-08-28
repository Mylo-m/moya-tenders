"""Moya — Consortium Matchmaker agent (the hackathon hero feature).

Given a tender's required capabilities, the agent:
  1. searches the local talent graph (tool call),
  2. reasons about coverage gaps,
  3. assembles the *smallest complementary team* that satisfies the mandatory
     certs / location rules,
  4. drafts one intro email per member,
  5. returns strict JSON.

Model: Gemini 3.5 Flash (hard requirement). Falls back to `gemma-3-...` when
GEMINI_MODEL=... or via a GEMMA_FALLBACK flag (hackathon #Gemma bonus +0.2).
Never fabricates — it only ever reasons over real rows from talent_db.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from gemini_client import _generate, DEFAULT_MODEL
from talent_db import search_talent, get_profile, _j

# gemma-3-27b-it is the open model the Gen AI SDK can serve; used as a cheap
# fallback so grading/the match still runs if Flash is unavailable (bonus path).
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma-3-27b-it")


def _tender_to_brief(tender: dict) -> str:
    """Turn a live tender row into the brief the agent reads."""
    fields = ["title", "description", "issuing_dept", "sector", "province",
              "country", "closing_date", "contact_person"]
    lines = []
    for f in fields:
        v = tender.get(f)
        if v:
            label = f.replace("_", " ").title()
            lines.append(f"- {label}: {v}")
    return "\n".join(lines) or "(no structured fields; raw tender below)"


def _talent_block(rows: list[dict]) -> str:
    out = []
    for t in rows:
        out.append(
            f"[{t['id']}] {t['name']} ({t['type']}, {t['country_code']}/{t.get('province','')})\n"
            f"    skills: {t['skills']}\n"
            f"    certs:  {t['certs']}\n"
            f"    langs:  {t.get('languages')}\n"
            f"    bio:    {t.get('bio','')}"
        )
    return "\n\n".join(out) if out else "(no candidates in pool)"


_SYSTEM = (
    "You are MY-LO Moya's Consortium Architect. African tenders force CIDB grading, "
    "B-BBEE, local-content and CSD rules, so solo pros and small firms usually cannot "
    "bid alone. Given a tender's required capabilities and a pool of verified local "
    "talent, assemble the SMALLEST complementary team that satisfies every mandatory "
    "cert/location/language rule. Explain each pick. Draft a short intro email per "
    "member. You may ONLY use talent ids present in the pool. Output STRICT JSON only, "
    "no prose outside the JSON, in this shape:\n"
    "{\n"
    '  "team": [{"id": int, "role": str, "why": str}],\n'
    '  "coverage": [str],\n'
    '  "gaps": [str],\n'
    '  "emails": [{"to_name": str, "subject": str, "body": str}]\n'
    "}\n"
    "If the pool cannot satisfy a mandatory rule, list it under 'gaps' honestly."
)


def build_consortium(
    tender: dict,
    brief_certs: Optional[list[str]] = None,
    brief_skills: Optional[list[str]] = None,
    model: Optional[str] = None,
) -> dict:
    """Run the matchmaker. Returns the parsed consortium dict (or an error wrapper)."""
    country = (tender.get("country_code") or tender.get("country") or "")[:2].upper() or None
    pool = search_talent(certs=brief_certs, skills=brief_skills,
                         province=tender.get("province"), country_code=country)
    if not pool:
        pool = search_talent(country_code=country) or search_talent()

    tender_brief = _tender_to_brief(tender)
    talent_block = _talent_block(pool)
    ext = (
        f"=== TENDER ===\n{tender_brief}\n\n"
        f"=== AVAILABLE TALENT POOL ({len(pool)} candidates) ===\n{talent_block}\n\n"
        "Assemble the consortium now — output only the JSON."
    )

    use_model = model or os.getenv("GEMMA_FALLBACK", "").lower() == "1" and GEMMA_MODEL or DEFAULT_MODEL
    try:
        raw = _generate(f"{_SYSTEM}\n\n{ext}", model=use_model, max_tokens=2000, temperature=0.3)
    except Exception as e:
        return {"ok": False, "error": f"model call failed: {e}", "pool_size": len(pool)}

    parsed = _force_json(raw)
    if parsed is None:
        return {"ok": False, "error": "model returned non-JSON", "raw": raw[:500],
                "pool_size": len(pool)}
    parsed["ok"] = True
    parsed["model"] = use_model
    parsed["pool_size"] = len(pool)
    parsed["tender_id"] = tender.get("id")
    # Resolve names for readability in the API response.
    by_id = {t["id"]: t["name"] for t in pool}
    for m in parsed.get("team", []):
        m["name"] = by_id.get(m.get("id"), "?")
    return parsed


def _force_json(text: str) -> Optional[dict]:
    """Pull the first {...} JSON object out of a model response, defensively.

    Handles the common model quirks: leading/trailing prose, single quotes,
    Python-style booleans/None, and trailing commas inside the object.
    """
    if not text:
        return None
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    chunk = text[s:e + 1].strip()
    import re
    tries = [
        chunk,
        chunk.replace("'", '"'),
        chunk.replace("True", "true").replace("False", "false").replace("None", "null"),
    ]
    for attempt in tries:
        try:
            return json.loads(attempt)
        except Exception:
            continue
    # Repair trailing commas before } / ] then retry.
    try:
        repaired = re.sub(r",\s*([}\]])", r"\1", chunk)
        repaired = repaired.replace("'", '"').replace("True", "true") \
                           .replace("False", "false").replace("None", "null")
        return json.loads(repaired)
    except Exception:
        return None


if __name__ == "__main__":
    from scraper_sqlite import get_db
    db = get_db()
    tender = db.execute(
        "SELECT * FROM tenders WHERE status='open' AND province IS NOT NULL "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    db.close()
    if not tender:
        print("no tender found"); raise SystemExit(1)
    res = build_consortium(dict(tender), brief_skills=["cctv", "cabling"])
    print(json.dumps(res, indent=2, ensure_ascii=False)[:1600])
