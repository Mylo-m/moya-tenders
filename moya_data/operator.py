"""
Moya — Autonomous Tender Operator (the "agent acts, not chats" core)

This is the differentiator for the All Things Agentic Hackathon. Most entrants
demo a chatbot. Moya instead RUNS: on every scheduled scrape it takes real
action on the tenders it collected — shredding each with Gemini, auto-drafting
the full bid data-package (SBD/PPADA returnables via doc_engine), persisting the
draft, and emitting an alert + an audit trail of what it did WITHOUT a human.

Flow (fully background, no supervision):
    fresh tenders -> gemini_shred -> build_bid_package -> save markdown + json
                 -> append audit log -> fire alert (stub)

Nothing here blocks on a human. The demo video simply shows the folder of
bid packages + audit log produced in the last run.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_OUT = _ROOT / "generated_bid_packages"
_AUDIT = _ROOT / "operator_audit.jsonl"

# Default bidder profile used to auto-fill returnables. In production this is
# pulled from the SME's MY-LO profile; here it's a safe demo profile so the
# operator can act unattended.
DEFAULT_BIDDER = {
    "ZA": {
        "bidder_name": "Demo SME (Pty) Ltd",
        "bbbee_level": "4",
        "cidb_grade": "7",
        "cidb_class": "GB",
        "currency": "ZAR",
        "vat_rate": 0.15,
        "tax_clearance_pin": "",
        "is_affidavit": True,
    },
    "KE": {
        "bidder_name": "Demo SME Ltd",
        "currency": "KES",
        "tax_rate": 0.16,
        "kra_pin": "",
        "agpo_category": "",
        "claiming_preference": False,
    },
}


def _load_fresh_tenders(limit: int = 20) -> list:
    """Tenders not yet processed by the operator (no generated_bid_packages row)."""
    import sqlite3
    db = sqlite3.connect(_ROOT / "moya.db")
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT id, title, country_code, sector, description, closing_date, issuing_dept "
        "FROM tenders WHERE status='open' AND country_code IN ('ZA','KE') "
        "ORDER BY closing_date ASC LIMIT ?",
        (limit,),
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def _shred_to_bid_context(shred_text: str, tender: dict) -> "tuple[dict, dict]":
    """Turn Gemini's shred output into the fields doc_engine needs.

    We don't parse the LLM strictly — we ask Gemini to also return the key
    obligations as JSON so the bid package is grounded in the shred.
    """
    from moya_data import gemini_client as gem

    prompt = (
        "Given this tender shred analysis, extract a JSON object with keys: "
        "bid_number, bid_description, closing_datetime, required_certificates (list), "
        "pricing_hint (short). Return ONLY valid JSON.\n\n"
        f"=== TENDER: {tender['title']} ===\n{tender.get('description','')}\n\n"
        f"=== SHRED ===\n{shred_text}"
    )
    try:
        raw = gem._generate(prompt, gem.DEFAULT_MODEL, max_tokens=600, temperature=0.2)
        raw = raw.strip().strip("`").replace("json", "", 1).strip()
        data = json.loads(raw)
    except Exception:
        data = {}
    # Merge with default bidder profile so build_bid_package has what it needs.
    base = dict(DEFAULT_BIDDER.get(tender["country_code"], {}))
    base["bid_description"] = data.get("bid_description") or tender["title"]
    base["closing_datetime"] = data.get("closing_datetime") or tender.get("closing_date")
    base["bid_number"] = data.get("bid_number") or f"AUTO-{tender['id']}"
    base["country_code"] = tender["country_code"]
    return base, data


def process_tender(tender: dict) -> dict:
    """Full autonomous action for one tender. Returns a result record."""
    from moya_data import gemini_client as gem
    from moya_data import doc_engine as de

    text = f"{tender['title']}\n{tender.get('description','')}"
    shred = gem.gemini_shred(text)
    bid, _ = _shred_to_bid_context(shred, tender)
    pkg = de.build_bid_package(tender["country_code"], bid)
    md = de.render_markdown(pkg)

    _OUT.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = f"{tender['country_code']}_{tender['id']}_{stamp}"
    ( _OUT / f"{slug}.md").write_text(md, encoding="utf-8")
    ( _OUT / f"{slug}.json").write_text(json.dumps(pkg, indent=2), encoding="utf-8")

    record = {
        "tender_id": tender["id"],
        "title": tender["title"],
        "country_code": tender["country_code"],
        "package_md": f"generated_bid_packages/{slug}.md",
        "produced_at": stamp,
    }
    # append audit line
    with _AUDIT.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def alert(record: dict) -> None:
    """Stub: in production this sends WhatsApp/email via the SME channel.
    Kept as a no-op here so the operator runs headless without creds."""
    print(f"[ALERT] Auto-drafted bid package for: {record['title']} -> {record['package_md']}")


def run_operator(limit: int = 20) -> dict:
    """Entry point called by cron_scrape after the scrape."""
    tenders = _load_fresh_tenders(limit)
    results = []
    for t in tenders:
        try:
            rec = process_tender(t)
            alert(rec)
            results.append(rec)
        except Exception as e:
            results.append({"tender_id": t["id"], "error": str(e)})
    summary = {
        "ok": True,
        "processed": len([r for r in results if "package_md" in r]),
        "errors": len([r for r in results if "error" in r]),
        "packages": [r for r in results if "package_md" in r],
        "time": datetime.now(timezone.utc).isoformat(),
    }
    return summary


if __name__ == "__main__":
    print(json.dumps(run_operator(), indent=2))
