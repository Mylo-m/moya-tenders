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
from fastapi.responses import JSONResponse, HTMLResponse

# Make moya_data importable (peer package).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from moya_data import gemini_client as gem  # noqa: E402
from moya_data import gcs_sync  # noqa: E402
from moya_data import cron_scrape as cs  # noqa: E402
from moya_data import matchmaker  # noqa: E402
from moya_data import talent_db  # noqa: E402
from moya_data import eligibility  # noqa: E402
from moya_data import vernacular  # noqa: E402
from moya_data import assess  # noqa: E402

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


@app.get("/api/talent")
def talent(
    country_code: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    limit: int = Query(40, le=100),
):
    rows = talent_db.search_talent(
        country_code=country_code, province=province, limit=limit
    )
    return {"ok": True, "count": len(rows), "talent": rows}


@app.post("/api/match")
def match(payload: dict):
    """Consortium Matchmaker — the hackathon hero endpoint.

    Body: {"tender_id": int}  OR  {"text": "tender brief...",
           "certs": [...], "skills": [...]}
    Calls Gemini 3.5 Flash (live), assembles a winning team from the talent
    graph, and persists the match JSON to Cloud Storage (when configured).
    """
    if not gem.gemini_configured():
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY not set — set it via Secret Manager / env.",
        )
    db = _db()
    try:
        tid = (payload or {}).get("tender_id")
        if tid:
            row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tender not found")
            tender = _row_to_dict(row)
            certs = (payload or {}).get("certs")
            skills = (payload or {}).get("skills")
        else:
            text = (payload or {}).get("text", "")
            if not text or not text.strip():
                raise HTTPException(status_code=400, detail="Need tender_id or text")
            tender = {
                "id": None, "title": "Inline brief", "description": text,
                "province": (payload or {}).get("province"),
                "country_code": (payload or {}).get("country_code"),
            }
            certs = (payload or {}).get("certs")
            skills = (payload or {}).get("skills") or [
                s.strip().lower() for s in text.split() if len(s) > 3
            ][:8]
    finally:
        db.close()

    try:
        result = matchmaker.build_consortium(tender, brief_certs=certs, brief_skills=skills)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Matchmaker error: {e}")

    if not result.get("ok"):
        return {"ok": False, "error": result.get("error"), "pool_size": result.get("pool_size")}

    # Persist the match to Cloud Storage (hackathon requirement #3) — no-op if unset.
    saved = gcs_sync.save_match(result)
    result["gcs_saved"] = saved
    return {"ok": True, "match": result}


@app.get("/match")
def match_ui():
    """Minimal demo UI: pick a tender, watch the agent build a consortium."""
    return HTMLResponse(_MATCH_UI_HTML)


@app.post("/api/eligibility")
def eligibility_check(payload: dict):
    """Eligibility Oracle (person level): 'Can I win this tender?'

    Body: {"tender_id": int, "profile_id": int}  OR
          {"text": "...", "profile_id": int, "country_code": "ZA"}
    Returns ELIGIBLE / NOT_ELIGIBLE / ELIGIBLE_IF with the exact certs to get.
    """
    if not gem.gemini_configured():
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY not set — set it via Secret Manager / env.",
        )
    db = _db()
    try:
        tid = (payload or {}).get("tender_id")
        pid = (payload or {}).get("profile_id")
        if not pid:
            raise HTTPException(status_code=400, detail="profile_id required")
        if tid:
            row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tender not found")
            tender = _row_to_dict(row)
        else:
            text = (payload or {}).get("text", "")
            if not text.strip():
                raise HTTPException(status_code=400, detail="Need tender_id or text")
            tender = {
                "id": None, "title": "Inline brief", "description": text,
                "country_code": (payload or {}).get("country_code", "ZA"),
            }
    finally:
        db.close()
    try:
        result = eligibility.evaluate_eligibility(tender, profile_id=int(pid))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Eligibility error: {e}")
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}
    return {"ok": True, "eligibility": result}


@app.post("/api/localize")
def localize(payload: dict):
    """Vernacular plain-language layer: plain summary + local-language translations.

    Body: {"tender_id": int}  OR  {"text": "...", "langs": ["zu","yo","sw"]}
    Produces a plain-language summary and translates it to isiZulu / Yoruba /
    Swahili / Amharic / French (the authentic-Africa moat).
    """
    if not gem.gemini_configured():
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not set.")
    db = _db()
    try:
        tid = (payload or {}).get("tender_id")
        if tid:
            row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tender not found")
            tender = _row_to_dict(row)
        else:
            text = (payload or {}).get("text", "")
            if not text.strip():
                raise HTTPException(status_code=400, detail="Need tender_id or text")
            tender = {"id": None, "title": "Inline brief", "description": text}
    finally:
        db.close()
    try:
        result = vernacular.localize_tender(tender, langs=(payload or {}).get("langs"), model=None)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Localize error: {e}")
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error")}
    return {"ok": True, "localized": result}


@app.post("/api/assess")
def assess_endpoint(payload: dict):
    """Unified Tender Assessment Orchestrator.

    One call chains: Eligibility (if profile_id given) -> Consortium Matchmaker
    -> Vernacular localization (if lang given). The full agentic tender desk.
    Body: {"tender_id": int, "profile_id": int, "lang": "zu"}
    """
    if not gem.gemini_configured():
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not set.")
    db = _db()
    try:
        tid = (payload or {}).get("tender_id")
        if tid:
            row = db.execute("SELECT * FROM tenders WHERE id=?", (tid,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Tender not found")
            tender = _row_to_dict(row)
        else:
            text = (payload or {}).get("text", "")
            if not text.strip():
                raise HTTPException(status_code=400, detail="Need tender_id or text")
            tender = {"id": None, "title": "Inline brief", "description": text,
                      "country_code": (payload or {}).get("country_code", "ZA")}
    finally:
        db.close()
    try:
        result = assess.assess_tender(
            tender,
            profile_id=(payload or {}).get("profile_id"),
            lang=(payload or {}).get("lang"),
            model=None,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Assess error: {e}")
    return {"ok": True, "assessment": result}


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


_MATCH_UI_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Moya — Agentic Tender Desk</title>
<style>
  body{font-family:system-ui,Arial,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;color:#16181d}
  h1{font-size:1.4rem} h2{font-size:1.05rem;margin-top:1.5rem}
  .card{border:1px solid #e2e2e2;border-radius:10px;padding:1rem;margin:.6rem 0}
  button{background:#1a73e8;color:#fff;border:0;border-radius:8px;padding:.6rem 1rem;font-size:.95rem;cursor:pointer}
  button:disabled{opacity:.5} input,textarea,select{width:100%;padding:.5rem;border:1px solid #ccc;border-radius:8px;box-sizing:border-box}
  pre{background:#0d1117;color:#c9d1d9;padding:1rem;border-radius:8px;overflow:auto;font-size:.78rem}
  .muted{color:#666;font-size:.85rem}
  #status{margin:.8rem 0;font-weight:600}
  .row{display:flex;gap:.6rem;flex-wrap:wrap}
  .row>div{flex:1;min-width:160px}
</style></head><body>
<h1>Moya — Agentic Tender Desk <span class="muted">(All Things Agentic Hackathon)</span></h1>
<p class="muted">One click runs the full agent: <b>Eligibility</b> (can you win alone?) →
<b>Consortium Matchmaker</b> (a winning team) → <b>Vernacular</b> (in your language), all on
Gemini 3.5 Flash.</p>
<div class="card">
  <div class="row">
    <div><label>Tender ID: <input id="tid" type="number" placeholder="e.g. 517"></label></div>
    <div><label>Your profile ID (1=Thabo,2=Naledi,3=Aisha): <input id="pid" type="number" placeholder="1" value="1"></label></div>
    <div><label>Language: <select id="lang">
      <option value="">English only</option>
      <option value="zu">isiZulu</option>
      <option value="yo">Yoruba</option>
      <option value="sw">Swahili</option>
      <option value="am">Amharic</option>
      <option value="fr">French</option>
    </select></label></div>
  </div>
  <button id="go" style="margin-top:.6rem">Assess tender &rarr;</button>
  <div id="status"></div>
</div>
<div class="card">
  <h2>…or paste a tender brief</h2>
  <textarea id="brief" rows="4" placeholder="Provision of structured cabling and CCTV at a Gauteng municipality. B-BBEE Level 4 required…"></textarea>
  <div class="row" style="margin-top:.6rem">
    <div><label>Profile ID: <input id="pid2" type="number" placeholder="1" value="1"></label></div>
    <div><label>Language: <select id="lang2">
      <option value="">English only</option>
      <option value="zu">isiZulu</option>
      <option value="yo">Yoruba</option>
      <option value="sw">Swahili</option>
      <option value="am">Amharic</option>
      <option value="fr">French</option>
    </select></label></div>
  </div>
  <button id="go2" style="margin-top:.6rem">Assess from brief &rarr;</button>
</div>
<h2>Result</h2>
<pre id="out">—</pre>
<script>
const api = (b)=>fetch('/api/assess',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})
  .then(r=>r.json());
function show(j){document.getElementById('out').textContent=JSON.stringify(j,null,2);}
document.getElementById('go').onclick=async()=>{
  const tid=document.getElementById('tid').value; if(!tid){alert('enter a tender id');return;}
  document.getElementById('status').textContent='⏳ running agents (eligibility → matchmaker → vernacular)…';
  show(await api({tender_id:Number(tid), profile_id:Number(document.getElementById('pid').value)||null, lang:document.getElementById('lang').value||null}));
  document.getElementById('status').textContent='✅ done';
};
document.getElementById('go2').onclick=async()=>{
  const t=document.getElementById('brief').value; if(!t.trim()){alert('paste a brief');return;}
  document.getElementById('status').textContent='⏳ running agents…';
  show(await api({text:t, profile_id:Number(document.getElementById('pid2').value)||null, lang:document.getElementById('lang2').value||null}));
  document.getElementById('status').textContent='✅ done';
};
</script></body></html>"""
