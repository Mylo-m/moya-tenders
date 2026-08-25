"""
MY-LO Moya — Cloud Run backend (the agentic tender desk API).

Deployed to Google Cloud Run. This is the "proof of deployment" backend the
All Things Agentic Hackathon judges require: it runs live on Google Cloud,
serves real tender data, and calls Gemini (via the official google-genai SDK)
in real time to shred tender documents.

Endpoints
  GET  /                       -> service banner
  GET  /api/health            -> liveness probe (Cloud Run healthcheck)
  GET  /api/tenders           -> live tender feed (filters: ?sector=&country_code=&q=)
  GET  /api/tenders/{id}      -> single tender
  GET  /api/stats             -> counts by country / sector (agent scraped these)
  POST /api/shred             -> {text: "..."} -> Gemini shreds it (real-time)

Run locally:  uvicorn moya_api.server:app --port 8000
Cloud Run:    gunicorn moya_api.server:app -b 0.0.0.0:$PORT
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

# Make moya_data importable (peer package).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from moya_data import gemini_client as gem  # noqa: E402
from moya_data import gcs_sync  # noqa: E402
from moya_data import cron_scrape as cs  # noqa: E402

# Hydrate the tender store from Cloud Storage on boot (no-op if unset / offline).
gcs_sync.pull_db()

# Protect the scheduled-scrape endpoint (set via CRON_SECRET on Cloud Run).
CRON_SECRET = os.getenv("CRON_SECRET", "")

app = FastAPI(title="MY-LO Moya — Agentic Tender Desk API", version="2.0.0")


def _db():
    """Open the tender SQLite store (source of truth scraped by moya_data)."""
    try:
        from moya_data.scraper_sqlite import get_db
        return get_db()
    except Exception:
        import sqlite3
        db_path = _ROOT / "moya_data" / "moya.db"
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        return db


def _row_to_dict(r) -> dict:
    return {k: r[k] for k in r.keys()}


@app.get("/")
def root():
    return {
        "service": "MY-LO Moya — Agentic Tender Desk",
        "built_for": "All Things Agentic Hackathon (Gemini API + Google Cloud)",
        "backend": "Google Cloud Run",
        "gemini_sdk": "google-genai",
        "gemini_configured": gem.gemini_configured(),
        "endpoints": ["/api/health", "/api/tenders", "/api/tenders/{id}", "/api/stats", "/api/shred"],
    }


@app.get("/api/health")
def health():
    return {"ok": True, "service": "moya-tender-desk", "time": _now()}


@app.get("/api/tenders")
def tenders(
    sector: Optional[str] = Query(None),
    country_code: Optional[str] = Query(None),
    q: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
):
    db = _db()
    try:
        sql = "SELECT * FROM tenders WHERE status='open'"
        params = []
        if sector:
            sql += " AND sector=?"
            params.append(sector)
        if country_code:
            sql += " AND country_code=?"
            params.append(country_code)
        if q:
            sql += " AND (title LIKE ? OR description LIKE ?)"
            params.extend([f"%{q}%", f"%{q}%"])
        sql += " ORDER BY closing_date ASC LIMIT ?"
        params.append(limit)
        rows = db.execute(sql, params).fetchall()
        return {"ok": True, "count": len(rows), "tenders": [_row_to_dict(r) for r in rows]}
    finally:
        db.close()


@app.get("/api/tenders/{tid}")
def tender_detail(tid: int):
    db = _db()
    try:
        row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Tender not found")
        return {"ok": True, "tender": _row_to_dict(row)}
    finally:
        db.close()


@app.get("/api/stats")
def stats():
    db = _db()
    try:
        by_country = db.execute(
            "SELECT country_code, COUNT(*) c FROM tenders GROUP BY country_code ORDER BY c DESC"
        ).fetchall()
        by_sector = db.execute(
            "SELECT sector, COUNT(*) c FROM tenders GROUP BY sector ORDER BY c DESC"
        ).fetchall()
        total = db.execute("SELECT COUNT(*) c FROM tenders").fetchone()["c"]
        return {
            "ok": True,
            "total_tenders": total,
            "by_country": [_row_to_dict(r) for r in by_country],
            "by_sector": [_row_to_dict(r) for r in by_sector],
        }
    finally:
        db.close()


@app.post("/api/shred")
def shred(payload: dict):
    """Real-time Gemini tender shredding — the agentic core, live on Cloud Run."""
    text = (payload or {}).get("text", "")
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Missing 'text'")
    if not gem.gemini_configured():
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY not set on this Cloud Run service — set it via Secret Manager / env.",
        )
    try:
        result = gem.gemini_shred(text)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")
    return {"ok": True, "engine": "gemini", "model": gem.DEFAULT_MODEL, "shred": result}


@app.post("/api/cron-scrape")
def cron_scrape(payload: dict = {}):
    """Triggered by Cloud Scheduler every 6h — pulls GCS, scrapes, pushes GCS."""
    secret = (payload or {}).get("secret", "")
    if not CRON_SECRET or secret != CRON_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")
    try:
        summary = cs.run_cron()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"scrape failed: {e}")
    return {"ok": True, "summary": summary}


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("moya_api.server:app", host="0.0.0.0", port=port)
