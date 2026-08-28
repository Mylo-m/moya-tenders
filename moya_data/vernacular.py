"""Moya — Vernacular Plain-Language Layer (the authentic-Africa moat).

Turns a 200-page tender into plain language AND translates the key bits into
local languages (isiZulu, Yoruba, Swahili, Amharic, French). Unlocks millions
of non-English seekers who currently can't read a tender.

Model: Gemini 3.5 Flash (live). No fabricated translation — Gemini produces it
from the real tender text. Graceful: if Gemini is down, returns the original
text so the agent never blocks on one missing dependency.
"""
from __future__ import annotations

import os
from typing import Optional

from gemini_client import _generate, DEFAULT_MODEL

# Languages we support for the authentic-Africa layer.
SUPPORTED_LANGS = {
    "en": "English (plain-language summary)",
    "zu": "isiZulu",
    "yo": "Yoruba",
    "sw": "Swahili",
    "am": "Amharic",
    "fr": "French",
}


def plain_language(tender_text: str, model: Optional[str] = None) -> str:
    """Summarise a tender into plain language a non-expert can understand."""
    system = (
        "You are MY-LO Moya's plain-language explainer for African government "
        "tenders. Rewrite the tender in simple, plain language a small-business "
        "owner with no procurement experience can understand. Cover: what is "
        "being asked for, who can apply, the deadline, what documents they need, "
        "and any tricky rules (B-BBEE, CIDB, local content). Be concise, friendly, "
        "and jargon-free. Do not invent details not in the text."
    )
    return _generate(f"{system}\n\n=== TENDER ===\n{tender_text[:110000]}", model=model or DEFAULT_MODEL, max_tokens=1200, temperature=0.3)


def translate(text: str, lang: str, model: Optional[str] = None) -> str:
    """Translate a short passage into a supported local language."""
    lang = lang.lower()
    if lang not in SUPPORTED_LANGS:
        raise ValueError(f"Unsupported lang '{lang}'. Supported: {list(SUPPORTED_LANGS)}")
    target = SUPPORTED_LANGS[lang]
    system = (
        f"You are MY-LO Moya's translator. Translate the given tender passage into "
        f"{target}. Keep proper nouns (company names, act names like B-BBEE, CIDB) "
        f"in their original form where no natural equivalent exists. Translate "
        f"accurately and naturally — do not add content. Output only the translation."
    )
    return _generate(f"{system}\n\n=== TEXT ===\n{text[:4000]}", model=model or DEFAULT_MODEL, max_tokens=800, temperature=0.3)


def localize_tender(tender: dict, langs: Optional[list[str]] = None, model: Optional[str] = None) -> dict:
    """Full localized package for one tender: plain summary + translations.

    `langs` is a list like ['zu','yo','sw']. Defaults to all local langs.
    """
    if not langs:
        langs = ["zu", "yo", "sw", "am", "fr"]
    body = (tender.get("description") or tender.get("title") or "")
    if not body.strip():
        return {"ok": False, "error": "tender has no text to localize"}

    try:
        summary = plain_language(body, model=model)
    except Exception as e:
        # Graceful: if Gemini is quota-limited, return the original text so the
        # agent never blocks on one missing dependency (resilience > demo polish).
        summary = f"(plain-language summary unavailable: {e})\n\nOriginal:\n{body[:1500]}"
    translations = {}
    for lg in langs:
        try:
            # Translate the plain summary (shorter, cleaner source for MT).
            translations[lg] = translate(summary[:3500], lg, model=model)
        except Exception as e:
            translations[lg] = f"(translation failed: {e})"

    return {
        "ok": True,
        "tender_id": tender.get("id"),
        "model": model or DEFAULT_MODEL,
        "plain_summary": summary,
        "translations": translations,
        "supported": SUPPORTED_LANGS,
    }


if __name__ == "__main__":
    from scraper_sqlite import get_db
    db = get_db()
    t = db.execute("SELECT * FROM tenders WHERE status='open' AND country_code='ZA' ORDER BY id DESC LIMIT 1").fetchone()
    db.close()
    out = localize_tender(dict(t), langs=["zu", "yo"])
    print("PLAIN:\n", out["plain_summary"][:700])
    for lg, txt in out["translations"].items():
        print(f"\n[{lg}]\n", txt[:400])
