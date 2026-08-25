#!/usr/bin/env python3
"""
Moya — Compliance Engine (Supplier Readiness Tracker)
=============================================================
Maps each client's supplier profile + certificates to the regulatory
ecosystems of the two deployment hubs, and dynamically evaluates bid-readiness
based on the client's COUNTRY selection.

South Africa (ZA):  CSD, Tax Clearance (PIN), B-BBEE, CIDB grading
Kenya (KE):         KRA Tax Compliance Certificate (iTax), BRS, AGPO

Design notes (2026-08-24):
- NO public government verification API exists for CSD/SARS/KRA/AGPO, so this
  engine is an INTERNAL TRACKER: the client records cert numbers + expiry, and
  the engine validates format, tracks validity/expiry, flags gaps, and produces
  a per-country readiness report. It does NOT call live gov systems.
- Rule sets are data-driven per country so adding a market is a dict edit.
- The schema (SupplierProfile + Certificate) is created in moya.db and
  keyed to the existing `users.id` (auth table in moya.php).

Run:  python3 compliance.py            # self-test on sample suppliers
      python3 compliance.py --demo     # also prints a rendered readiness report
"""

import os
import re
import sqlite3
from datetime import datetime, date


DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'moya.db')


# ---------------------------------------------------------------------------
# REGISTRY: per-country certificate definitions
# Each cert: key, label, issuing authority, format regex, validity hint, AGPO-linked?
# ---------------------------------------------------------------------------
COMPLIANCE_REGISTRY = {
    "ZA": {
        "label": "South Africa",
        "authority": "National Treasury / SARS / CIDB",
        "certs": {
            "csd": {
                "label": "CSD Registration (Central Supplier Database)",
                "authority": "National Treasury",
                "regex": r"^[A-Za-z0-9]{6,20}$",            # MAAA-style supplier code
                "required": True,
                "expiry_tracked": True,
                "hint": "CSD supplier registration number; renewed on the CSD portal.",
            },
            "tax_clearance": {
                "label": "Tax Clearance PIN (SARS)",
                "authority": "SARS",
                "regex": r"^[0-9]{9,10}$",                  # tax reference number
                "required": True,
                "expiry_tracked": True,                     # Tax Compliance Status PIN valid 12 months
                "hint": "SARS Tax Compliance Status PIN; valid 12 months from issue.",
            },
            "bbbee": {
                "label": "B-BBEE Status (Certificate or Affidavit)",
                "authority": "B-BBEE Commission / dti",
                "regex": r"^(1|2|3|4|5|8|N/A)$",            # contributor level 1-5, 8 (non-compliant), or Affidavit
                "format_field": "cert_level",               # validation applies to the level, not the cert no.
                "required": True,
                "expiry_tracked": True,                     # certificate valid 1 year; affidavit 1 year (EME/QSE)
                "hint": "Contributor level 1-5, level 8, or sworn affidavit (EME/QSE < R50m).",
                "levels": ["1", "2", "3", "4", "5", "8"],
            },
            "cidb": {
                "label": "CIDB Grading (Construction/Infrastructure)",
                "authority": "CIDB",
                "regex": r"^(9|8|7|6|5|4|3|2|1)\s?(GB|CE|EB|SB|SP|SD|SQ|SM)$",
                "format_field": "cert_level",               # grading is the level (e.g. 9GB)
                "required": False,                          # only for construction bids
                "expiry_tracked": True,                     # grading valid 3 years
                "hint": "e.g. 9GB (highest general building) or 1CE-9CE. Needed only for construction/infra bids.",
                "conditional_on_sector": "construction",
            },
        },
    },
    "KE": {
        "label": "Kenya",
        "authority": "KRA / BRS / Treasury (PPADA)",
        "certs": {
            "kra_tcc": {
                "label": "KRA Tax Compliance Certificate (iTax)",
                "authority": "Kenya Revenue Authority",
                "regex": r"^[A-Z]{1}[0-9]{9}[A-Z]{1}$",     # KRA PIN format (e.g. A123456789B)
                "required": True,
                "expiry_tracked": True,                     # TCC valid 12 months
                "hint": "KRA PIN (A123456789B) + Tax Compliance Certificate valid 12 months via iTax.",
            },
            "brs": {
                "label": "BRS Registration No. (Business Registration Service)",
                "authority": "BRS Kenya",
                "regex": r"^(CPR|[A-Z]{1,3})[-/]?[0-9]{5,7}$",  # certificate of incorporation / business no
                "required": True,
                "expiry_tracked": False,
                "hint": "BRS registration number from e-citizen / BRS portal.",
            },
            "agpo": {
                "label": "AGPO Certificate (Youth / Women / PWD)",
                "authority": "Treasury (AGPO)",
                "regex": r"^(YOUTH|WOMEN|PWD)-?[A-Z0-9]{4,15}$",
                "required": False,                         # optional preferential access
                "expiry_tracked": True,                    # AGPO certificate valid 12 months
                "hint": "Access to Government Procurement Opportunities cert for Youth, Women, or Persons with Disabilities.",
                "categories": ["YOUTH", "WOMEN", "PWD"],
            },
        },
    },
}


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def ensure_compliance_tables():
    """Attach supplier profiles + certificates to moya.db (keyed to users.id)."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            country_code TEXT NOT NULL,
            legal_name TEXT NOT NULL,
            registration_no TEXT,
            tax_no TEXT,
            sector TEXT,
            contact_email TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS certificates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_id INTEGER NOT NULL,
            country_code TEXT NOT NULL,
            cert_key TEXT NOT NULL,
            cert_number TEXT,
            cert_level TEXT,            -- B-BBEE level / CIDB grade / AGPO category
            issued_date TEXT,
            expiry_date TEXT,
            status TEXT DEFAULT 'unknown',   -- valid | expiring | expired | missing | invalid
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        );
        CREATE INDEX IF NOT EXISTS idx_certs_supplier ON certificates(supplier_id);
        CREATE INDEX IF NOT EXISTS idx_suppliers_user ON suppliers(user_id);
    """)
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_format(country_code, cert_key, value):
    """Return (ok, msg). Checks the cert's regex (if defined)."""
    spec = COMPLIANCE_REGISTRY.get(country_code, {}).get("certs", {}).get(cert_key)
    if not spec:
        return False, "Unknown certificate key for country"
    rx = spec.get("regex")
    if rx and value:
        if not re.match(rx, str(value).strip()):
            return False, f"Format invalid for {spec['label']}"
    return True, "ok"


def evaluate_cert(spec, cert_row):
    """Given a cert spec + stored cert row, return a status dict."""
    value = (cert_row["cert_number"] or "").strip() if cert_row else ""
    level = (cert_row["cert_level"] or "").strip() if cert_row else ""
    expiry = (cert_row["expiry_date"] or "").strip() if cert_row else ""
    issued = (cert_row["issued_date"] or "").strip() if cert_row else ""

    if not cert_row or not value:
        return {"status": "missing", "msg": "Not recorded", "valid": False}
    # Format validation targets cert_number by default, or cert_level for graded certs
    fmt_field = spec.get("format_field", "cert_number")
    fmt_val = (cert_row["cert_level"] or "").strip() if fmt_field == "cert_level" else value
    rx = spec.get("regex")
    if rx and fmt_val and not re.match(rx, str(fmt_val).strip()):
        return {"status": "invalid", "msg": f"Format invalid for {spec['label']}", "valid": False}
    ok, msg = True, "ok"
    if not ok:
        return {"status": "invalid", "msg": msg, "valid": False}
    # expiry evaluation
    if spec.get("expiry_tracked"):
        exp = _parse_date(expiry)
        if exp is None:
            return {"status": "unknown", "msg": "No expiry date recorded", "valid": False}
        today = date.today()
        if exp < today:
            return {"status": "expired", "msg": f"Expired {exp.isoformat()}", "valid": False}
        if (exp - today).days <= 30:
            return {"status": "expiring", "msg": f"Expires {exp.isoformat()} (<=30d)", "valid": True}
        return {"status": "valid", "msg": f"Valid to {exp.isoformat()}", "valid": True}
    # not expiry-tracked but format-valid
    return {"status": "valid", "msg": "Recorded (no expiry)", "valid": True}


def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Readiness report — the core product
# ---------------------------------------------------------------------------
def evaluate_supplier(supplier_id):
    db = get_db()
    sup = db.execute("SELECT * FROM suppliers WHERE id=?", (supplier_id,)).fetchone()
    if not sup:
        db.close()
        return None
    cc = sup["country_code"]
    reg = COMPLIANCE_REGISTRY.get(cc)
    if not reg:
        db.close()
        return {"error": f"No registry for country {cc}"}

    certs = db.execute("SELECT * FROM certificates WHERE supplier_id=?", (supplier_id,)).fetchall()
    cert_by_key = {c["cert_key"]: c for c in certs}

    results = []
    for key, spec in reg["certs"].items():
        row = cert_by_key.get(key)
        ev = evaluate_cert(spec, row)
        # conditional certs only matter if the supplier is in that sector
        conditional = spec.get("conditional_on_sector")
        applicable = True
        if conditional:
            applicable = (sup["sector"] == conditional)
        results.append({
            "key": key,
            "label": spec["label"],
            "authority": spec["authority"],
            "required": spec.get("required", False),
            "conditional": conditional,
            "applicable": applicable,
            "status": ev["status"],
            "msg": ev["msg"],
            "valid": ev["valid"] and (applicable or not spec.get("required")),
            "hint": spec.get("hint", ""),
        })

    # readiness score: required+applicable certs that are valid
    needed = [r for r in results if r["required"] and r["applicable"]]
    passed = [r for r in needed if r["status"] in ("valid", "expiring")]
    score = round(100 * len(passed) / len(needed), 1) if needed else 100.0
    gaps = [r for r in results if r["status"] in ("missing", "invalid", "expired") and r["required"] and r["applicable"]]
    ready = score >= 100.0 and not gaps

    db.close()
    return {
        "supplier_id": supplier_id,
        "legal_name": sup["legal_name"],
        "country": reg["label"],
        "country_code": cc,
        "authority": reg["authority"],
        "score": score,
        "ready": ready,
        "certs": results,
        "gaps": gaps,
    }


def evaluate_all():
    db = get_db()
    ids = [r["id"] for r in db.execute("SELECT id FROM suppliers").fetchall()]
    db.close()
    return [evaluate_supplier(i) for i in ids]


# ---------------------------------------------------------------------------
# CLI self-test / demo
# ---------------------------------------------------------------------------
def _seed_demo():
    ensure_compliance_tables()
    db = get_db()
    today = date.today()
    soon = (today.replace(day=1) if today.day > 5 else today)
    future = date(today.year + 1, today.month, today.day).isoformat()
    expired = date(today.year - 1, today.month, today.day).isoformat()

    # South African supplier — fully ready (construction, with CIDB)
    db.execute("INSERT OR REPLACE INTO suppliers (id, user_id, country_code, legal_name, registration_no, tax_no, sector, contact_email) VALUES (?,?,?,?,?,?,?,?)",
               (1, 1, "ZA", "Cape Tech Solutions (Pty) Ltd", "CSD998877", "9123456789", "construction", "ops@capetech.co.za"))
    db.execute("DELETE FROM certificates WHERE supplier_id=1")
    for c in [
        (1, "ZA", "csd", "CSD998877", "", "", future),
        (1, "ZA", "tax_clearance", "9123456789", "", "", future),
        (1, "ZA", "bbbee", "BBBEE12345", "4", "", future),
        (1, "ZA", "cidb", "9GB", "", "", future),
    ]:
        db.execute("INSERT INTO certificates (supplier_id, country_code, cert_key, cert_number, cert_level, issued_date, expiry_date) VALUES (?,?,?,?,?,?,?)",
                   (c[0], c[1], c[2], c[3], c[4], expired, c[6]))

    # Kenyan supplier — missing AGPO (optional) but KRA+BRS valid (ready)
    db.execute("INSERT OR REPLACE INTO suppliers (id, user_id, country_code, legal_name, registration_no, tax_no, sector, contact_email) VALUES (?,?,?,?,?,?,?,?)",
               (2, 2, "KE", "Nairobi Digital Ltd", "CPR123456", "A123456789B", "ict", "ceo@nairobidigital.co.ke"))
    db.execute("DELETE FROM certificates WHERE supplier_id=2")
    for c in [
        (2, "KE", "kra_tcc", "A123456789B", "", "", future),
        (2, "KE", "brs", "CPR123456", "", "", ""),
        (2, "KE", "agpo", "", "", "", ""),  # missing optional
    ]:
        db.execute("INSERT INTO certificates (supplier_id, country_code, cert_key, cert_number, cert_level, issued_date, expiry_date) VALUES (?,?,?,?,?,?,?)",
                   (c[0], c[1], c[2], c[3], c[4], expired, c[6]))

    # South African supplier — expired tax clearance (NOT ready)
    db.execute("INSERT OR REPLACE INTO suppliers (id, user_id, country_code, legal_name, registration_no, tax_no, sector, contact_email) VALUES (?,?,?,?,?,?,?,?)",
               (3, 3, "ZA", "Gauteng Logistics CC", "CSD556677", "9111222333", "logistics", "admin@glogs.co.za"))
    db.execute("DELETE FROM certificates WHERE supplier_id=3")
    for c in [
        (3, "ZA", "csd", "CSD556677", "", "", future),
        (3, "ZA", "tax_clearance", "9111222333", "", "", expired),  # EXPIRED
        (3, "ZA", "bbbee", "BBBEE998", "5", "", future),
    ]:
        db.execute("INSERT INTO certificates (supplier_id, country_code, cert_key, cert_number, cert_level, issued_date, expiry_date) VALUES (?,?,?,?,?,?,?)",
                   (c[0], c[1], c[2], c[3], c[4], expired, c[6]))

    db.commit()
    db.close()


def _print_report(rep):
    if not rep:
        return
    print(f"\n=== {rep['legal_name']}  ({rep['country']} / {rep['country_code']}) ===")
    print(f"Authority: {rep['authority']}")
    print(f"Readiness: {rep['score']}%   {'✅ READY TO BID' if rep['ready'] else '⛔ NOT READY'}")
    for r in rep["certs"]:
        flag = {"valid": "✅", "expiring": "⚠️", "expired": "❌", "missing": "❌", "invalid": "❌", "unknown": "❓"}.get(r["status"], "?")
        req = "REQ" if r["required"] else "opt"
        cond = f" [sector:{r['conditional']}]" if r["conditional"] else ""
        print(f"  {flag} [{req}]{cond} {r['label']}: {r['status']} — {r['msg']}")
    if rep["gaps"]:
        print("  GAPS:")
        for g in rep["gaps"]:
            print(f"    - {g['label']}: {g['msg']}")
    print(f"  Hint: {rep['certs'][0]['hint'][:0]}")  # noop, keep layout


if __name__ == "__main__":
    import sys
    _seed_demo()
    reps = evaluate_all()
    print(f"Compliance Engine — evaluated {len(reps)} supplier(s)\n")
    for rep in reps:
        _print_report(rep)
    print("\nRegistry covers: " + ", ".join(f"{k}={v['label']} ({len(v['certs'])} certs)" for k, v in COMPLIANCE_REGISTRY.items()))
