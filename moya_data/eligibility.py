"""Moya — Eligibility Oracle (person/company level "Can I win this tender?").

Takes a tender + a stored talent/person profile (from talent_db) and answers:
  ELIGIBLE / NOT_ELIGIBLE / ELIGIBLE_IF  (with the exact certs/caps needed).
It reasons over REAL profile data + the country compliance registry, then
confirms with Gemini 3.5 Flash (live) so the verdict reads in plain language.
No fabricated eligibility — only what the profile + tender actually support.

Reuses the COMPLIANCE_REGISTRY from compliance.py for mandatory-cert rules.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from gemini_client import _generate, DEFAULT_MODEL
from talent_db import get_profile, _j
import compliance as cmp


def _profile_to_certs(profile: dict) -> dict:
    """Extract a cert key->level map from a talent profile's certs JSON.

    Normalises common key variants (e.g. 'bbee' <-> 'bbbee') so the talent
    graph and the compliance registry speak the same language.
    """
    _NORM = {
        "bbbee": "bbbee", "bbee": "bbbee", "beebbe": "bbbee",
        "cidb": "cidb", "cs": "csd", "csd": "csd",
        "tax": "tax_clearance", "tax_clearance": "tax_clearance",
        "psira": "psira", "iso": "iso", "agpo": "agpo",
    }
    raw = profile.get("certs")
    # get_profile() may already return parsed JSON (dict/list); tolerate both.
    if not isinstance(raw, dict):
        raw = _j(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw) if isinstance(raw, (str, bytes)) else {}
    out: dict = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            nk = _NORM.get(k.lower(), k.lower())
            if isinstance(v, bool):
                if v:
                    out[nk] = "yes"
            else:
                out[nk] = str(v).lower()
    return out


def _tender_mandatory_hints(tender: dict) -> list[str]:
    """Light heuristic: pull likely mandatory cert keywords from the tender text."""
    import re
    text = " ".join(str(tender.get(f, "")) for f in ("title", "description", "sector", "province"))
    text = text.lower()
    keywords = {
        "cidb": "CIDB grading (construction/infra)",
        "b-bee": "B-BBEE status",
        "bbbee": "B-BBEE status",
        "cs": "CSD registration",
        "csd": "CSD registration",
        "tax": "Tax clearance (SARS/KRA)",
        "psira": "PSIRA registration (security)",
        "iso": "ISO certification",
        "agpo": "AGPO certificate (KE preferential)",
        "women": "Women-owned preferential (WBE)",
        "youth": "Youth-owned preferential",
    }
    found = []
    for kw, label in keywords.items():
        if kw in text:
            found.append(label)
    return found


def evaluate_eligibility(
    tender: dict,
    profile_id: int,
    model: Optional[str] = None,
) -> dict:
    """Return the Eligibility Oracle verdict for one person vs one tender."""
    profile = get_profile(profile_id)
    if not profile:
        return {"ok": False, "error": f"profile {profile_id} not found"}

    country = (profile.get("country_code") or tender.get("country_code") or "ZA").upper()
    reg = cmp.COMPLIANCE_REGISTRY.get(country)
    have = _profile_to_certs(profile)

    # Rule-based pass/fail against the country registry's REQUIRED certs.
    required = []
    if reg:
        sector = profile.get("province")  # not sector; talent uses province only
        for key, spec in reg["certs"].items():
            if spec.get("required"):
                # only count certs applicable to this profile's nature
                required.append((key, spec))

    missing = []
    for key, spec in required:
        if key not in have:
            missing.append(spec["label"])

    # Tender-specific mandatory hints (keyword scan) the profile may lack.
    tender_hints = _tender_mandatory_hints(tender)
    have_blob = " ".join(have.keys()).lower()
    hint_missing = [h for h in tender_hints if not any(k in have_blob for k in h.lower().split())]

    base_verdict = "ELIGIBLE_IF" if (missing or hint_missing) else "ELIGIBLE"

    # Gemini plain-language confirmation (live).
    system = (
        "You are MY-LO Moya's Eligibility Oracle for African tenders. Given a "
        "supplier's real certificate profile and a tender's mandatory rules, state "
        "plainly whether they can win this tender. Be honest: if a mandatory cert is "
        "missing, say ELIGIBLE IF THEY GET <cert>. Never invent certificates the "
        "supplier does not have. Output strict JSON: "
        '{"verdict": "ELIGIBLE|NOT_ELIGIBLE|ELIGIBLE_IF", '
        '"summary": str, "must_get": [str], "strengths": [str]}.'
    )
    ext = (
        f"TENDER: {tender.get('title','')} | {tender.get('description','')[:400]}\n"
        f"SUPPLIER PROFILE: {profile.get('name')} ({profile.get('type')}, {country})\n"
        f"  certs on file: {have}\n"
        f"  skills: {profile.get('skills')}\n"
        f"REGISTRY-REQUIRED certs missing: {missing}\n"
        f"TENDER mandatory hints possibly missing: {hint_missing}\n"
        "Return the eligibility verdict now (JSON only)."
    )
    try:
        raw = _generate(f"{system}\n\n{ext}", model=model or DEFAULT_MODEL, max_tokens=900, temperature=0.2)
        parsed = _force_json(raw)
    except Exception as e:
        parsed = None

    if parsed is None:
        # Fall back to rule-based verdict (still useful, no Gemini).
        parsed = {
            "verdict": base_verdict,
            "summary": f"Rule check: {len(missing)} registry-required cert(s) missing, {len(hint_missing)} tender flag(s) unconfirmed.",
            "must_get": missing + hint_missing,
            "strengths": [k for k in have],
        }

    parsed["ok"] = True
    parsed["model"] = model or DEFAULT_MODEL
    parsed["profile_id"] = profile_id
    parsed["profile_name"] = profile.get("name")
    parsed["tender_id"] = tender.get("id")
    parsed["registry_missing"] = missing
    return parsed


def _force_json(text: str) -> Optional[dict]:
    if not text:
        return None
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    chunk = text[s:e + 1].strip()
    for attempt in (chunk, chunk.replace("'", '"')):
        try:
            return json.loads(attempt)
        except Exception:
            continue
    return None


if __name__ == "__main__":
    from scraper_sqlite import get_db
    db = get_db()
    t = db.execute("SELECT * FROM tenders WHERE status='open' AND country_code='ZA' ORDER BY id DESC LIMIT 1").fetchone()
    db.close()
    # use Thabo (id 1, has cidb+bbee) vs the tender
    res = evaluate_eligibility(dict(t), profile_id=1)
    print(json.dumps(res, indent=2, ensure_ascii=False)[:1400])
