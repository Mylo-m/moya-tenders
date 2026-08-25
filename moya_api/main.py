"""
MY-LO Moya — Tool #4: Quote & Proposal Generator API
=====================================================

FastAPI service exposing:
    POST /api/moya/proposal-gen        -> generate a branded PDF, return a
                                          secure, expiring download link
    GET  /api/moya/proposal-download/{token} -> download the generated PDF
    GET  /api/moya/counters            -> live portal counters (incl.
                                          proposals_generated_count)
    GET  /api/moya/health              -> liveness probe

Run:  uvicorn moya_api.main:app --reload --port 8000
      (from the mylo_site/ directory)
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the project root (which holds the `services` package) is importable.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, HTTPException, Path as PathParam  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel, Field, field_validator  # noqa: E402

from services.proposal_gen import generate_proposal_pdf  # noqa: E402
from services import state_tracker  # noqa: E402

# Where the token->path map lives (so it survives restarts).
_TOKEN_MAP_PATH = _ROOT / "moya_data" / "proposal_downloads.json"
_DOWNLOAD_TTL_HOURS = 24  # secure links expire after 24h

app = FastAPI(
    title="MY-LO Moya — Proposal Generator API",
    description="Branded PDF quote/proposal generation for the MY-LO Moya portal.",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class LineItem(BaseModel):
    description: str = Field(..., min_length=1, description="Line item description")
    qty: float = Field(1, gt=0, description="Quantity")
    unit_price: float = Field(..., ge=0, description="Unit price (excl. VAT)")
    vat_rate: Optional[float] = Field(None, ge=0, le=1,
                                      description="Per-line VAT rate override (0-1)")


class ProposalMeta(BaseModel):
    title: Optional[str] = None
    proposal_number: Optional[str] = None
    valid_until: Optional[str] = None
    prepared_by: Optional[str] = None
    currency: str = "ZAR"
    vat_rate: float = Field(0.15, ge=0, le=1)
    discount: float = Field(0.0, ge=0)


class ClientData(BaseModel):
    client_name: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    prepared_by: Optional[str] = None
    date: Optional[str] = None
    valid_until: Optional[str] = None
    proposal_meta: Optional[ProposalMeta] = None
    scope_of_work: Optional[Any] = None
    terms: Optional[Any] = None

    @field_validator("scope_of_work", "terms", mode="before")
    @classmethod
    def _allow_str_or_list(cls, v):
        return v


class ProposalRequest(BaseModel):
    client: ClientData
    line_items: List[LineItem] = Field(..., min_length=1,
                                       description="At least one line item required")


# ---------------------------------------------------------------------------
# Token map persistence
# ---------------------------------------------------------------------------
def _load_tokens() -> Dict[str, dict]:
    if _TOKEN_MAP_PATH.exists():
        try:
            with _TOKEN_MAP_PATH.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def _save_tokens(data: Dict[str, dict]) -> None:
    _TOKEN_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _TOKEN_MAP_PATH.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh)
    os.replace(tmp, _TOKEN_MAP_PATH)


def _issue_token(pdf_path: str) -> str:
    tokens = _load_tokens()
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(24)
    tokens[token] = {
        "path": pdf_path,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=_DOWNLOAD_TTL_HOURS)).isoformat(),
    }
    _save_tokens(tokens)
    return token


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/api/moya/health")
def health():
    return {"ok": True, "service": "proposal-gen", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/moya/counters")
def counters():
    return {"ok": True, "counters": state_tracker.get_counters()}


@app.post("/api/moya/proposal-gen")
def proposal_gen(req: ProposalRequest):
    client = req.client.model_dump(exclude_none=True)
    line_items = [li.model_dump() for li in req.line_items]

    # Flatten proposal_meta into client_data so the generator sees it.
    if req.client.proposal_meta:
        client["proposal_meta"] = req.client.proposal_meta.model_dump(exclude_none=True)

    try:
        pdf_path = generate_proposal_pdf(client, line_items)
    except Exception as exc:  # surface a clean 500 with the reason
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")

    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=500, detail="PDF was not written to disk.")

    token = _issue_token(pdf_path)
    count = state_tracker.get_counter("proposals_generated_count")

    return {
        "ok": True,
        "proposal_number": (req.client.proposal_meta.proposal_number
                            if req.client.proposal_meta and req.client.proposal_meta.proposal_number
                            else Path(pdf_path).stem),
        "pdf_path": pdf_path,
        "download_url": f"/api/moya/proposal-download/{token}",
        "expires_in_hours": _DOWNLOAD_TTL_HOURS,
        "proposals_generated_count": count,
    }


@app.get("/api/moya/proposal-download/{token}")
def proposal_download(token: str = PathParam(..., description="Signed, expiring download token")):
    tokens = _load_tokens()
    rec = tokens.get(token)
    if not rec:
        raise HTTPException(status_code=404, detail="Invalid or expired download link.")
    expires = datetime.fromisoformat(rec["expires_at"])
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=410, detail="Download link has expired.")
    path = rec["path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="PDF no longer available.")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=os.path.basename(path),
        headers={"Content-Disposition": f'attachment; filename="{os.path.basename(path)}"'},
    )
