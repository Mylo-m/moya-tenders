"""
Moya - Gemini client (All Things Agentic Hackathon: Gemini API + Google Cloud).

Uses the OFFICIAL Google Gen AI SDK (`google-genai`) when available — one of
the four sanctioned developer tools for the hackathon (ADK / Gen AI SDK /
Antigravity / Genkit). Falls back to the stable v1beta REST endpoint if the
SDK is not installed, so the service still runs.

Credential: GEMINI_API_KEY in the environment (never hardcoded, never committed).
Model: defaults to gemini-3.5-flash; override via GEMINI_MODEL.
"""

from __future__ import annotations

import json
import os

# --- Load MYLO .env so GEMINI_API_KEY is available without a manual export ---
def _load_mylo_env():
    """Best-effort loader for the MYLO .env (no external deps).

    Reads the first existing candidate file and injects any keys not already
    present in os.environ. This keeps local runs (shim, uvicorn, __main__)
    working without the Cloud Run bootstrap that sets env vars for us.
    """
    candidates = [
        os.environ.get("MYLO_ENV_PATH"),
        "/mnt/c/Users/ordio/.env",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),
    ]
    for cand in candidates:
        if not cand or not os.path.exists(cand):
            continue
        try:
            with open(cand, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip(), v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            pass
        return  # first existing file wins

_load_mylo_env()

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

# Cap input so large pasted tender docs don't blow the request size/latency.
_MAX_INPUT_CHARS = 120000

# ---------------------------------------------------------------------------
# SDK path (preferred) — google-genai is a sanctioned hackathon tool
# ---------------------------------------------------------------------------
def _genai_client():
    """Return a configured google-genai client, or None if unavailable."""
    try:
        from google import genai
    except Exception:
        return None
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        return genai.Client(api_key=key)
    except Exception:
        return None


def gemini_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def _generate(prompt: str, model: str, max_tokens: int = 1500, temperature: float = 0.4) -> str:
    client = _genai_client()
    if client is not None:
        try:
            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config={"max_output_tokens": max_tokens, "temperature": temperature},
            )
            text = getattr(resp, "text", None)
            if text:
                return text
            # Some SDK shapes nest candidates; be defensive.
            cands = getattr(resp, "candidates", None)
            if cands:
                return cands[0].content.parts[0].text
            raise RuntimeError("Gen AI SDK returned no content")
        except Exception:
            # fall through to REST below
            pass

    # ---- REST fallback (stable v1beta generateContent) ----
    import urllib.request
    import urllib.error
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set in environment")
    if len(prompt) > _MAX_INPUT_CHARS:
        prompt = prompt[:_MAX_INPUT_CHARS] + "\n[...truncated]"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }).encode("utf-8")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    import time as _time
    last_err = None
    # Up to 4 attempts with exponential backoff (handles 429 quota bursts).
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except urllib.error.HTTPError as e:
            body_err = e.read().decode("utf-8", "replace")[:200]
            if e.code == 429:
                # Quota/rate limit — back off and retry.
                last_err = f"Gemini HTTP 429 (quota): {body_err}"
                _time.sleep(2 ** attempt + 1)
                continue
            raise RuntimeError(f"Gemini HTTP {e.code}: {body_err}")
        except Exception as e:
            last_err = e
            _time.sleep(2 ** attempt)
            continue
    raise RuntimeError(f"Gemini call failed after retries: {last_err}")


def gemini_shred(tender_text: str, model: str = DEFAULT_MODEL) -> str:
    """Shred a tender document into structured requirements via Gemini."""
    system = (
        "You are MY-LO Moya's tender-shredding engine for African government "
        "and enterprise procurement. Given a tender document, extract: "
        "(1) key obligations, (2) submission deadline, (3) required compliance "
        "certificates (e.g. B-BBEE, CIDB, CSD, tax clearance, PSIRA, ISO), "
        "(4) mandatory returnable forms, (5) penalties/risks, and "
        "(6) a plain-language bid-readiness checklist. Be concise and structured."
    )
    return _generate(f"{system}\n\n=== TENDER DOCUMENT ===\n{tender_text[:_MAX_INPUT_CHARS]}", model)


def gemini_draft(tender_text: str, buyer_name: str = "", model: str = DEFAULT_MODEL) -> str:
    """Draft a first-pass bid response package summary via Gemini."""
    system = (
        "You are MY-LO Moya's bid-drafting assistant. Given a tender and the "
        "bidder's profile, produce a structured bid outline: cover note, "
        "compliance attestations, pricing table skeleton, and a list of "
        "documents the bidder must still supply. Output clean markdown."
    )
    return _generate(f"{system}\n\nBidder: {buyer_name}\n\n=== TENDER ===\n{tender_text[:_MAX_INPUT_CHARS]}", model)


if __name__ == "__main__":
    if not gemini_configured():
        print("NOT_CONFIGURED: set GEMINI_API_KEY")
        raise SystemExit(2)
    out = gemini_shred(
        "Provision of structured cabling and CCTV at a Gauteng municipality. "
        "B-BBEE Level 4 required. Compulsory site briefing on 15 September 2026. "
        "Closing 30 September 2026."
    )
    print("GEMINI_OK")
    print(out[:700])
