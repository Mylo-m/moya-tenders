"""Moya — talent graph store (the two-sided 'opportunity <-> talent' network).

Adds a `talent` table to the live moya.db and exposes the two tools the
Consortium Matchmaker agent calls:
  - search_talent(certs?, skills?, province?, country?) -> candidate rows
  - get_profile(id)                                     -> full profile

No external deps. All calls are local-SQLite so this runs offline; the agent
layer (matchmaker.py) is what talks to Gemini / Cloud Storage.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent / "moya.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS talent (
  id            INTEGER PRIMARY KEY,
  name          TEXT,
  type          TEXT,          -- 'individual' | 'company'
  country_code  TEXT,          -- ZA, KE, NG, ...
  province      TEXT,          -- Gauteng, Nairobi, Lagos ...
  skills        TEXT,          -- JSON array: ['q-sys','crestron','cisco']
  certs         TEXT,          -- JSON: {'cidb':'9','bbee':'1','qsys':true}
  languages     TEXT,          -- JSON: ['en','zu','yo']
  rate_day      INTEGER,       -- day rate ZAR (optional)
  available     INTEGER,       -- 1 = open to work
  contact       TEXT,          -- email / WhatsApp (redacted until accept in prod)
  bio           TEXT
);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def _j(js: Optional[str]):
    try:
        return json.loads(js) if js else []
    except Exception:
        return []


def talent_count() -> int:
    try:
        return _conn().execute("SELECT COUNT(*) c FROM talent").fetchone()["c"]
    except Exception:
        return 0


def search_talent(
    certs: Optional[list[str]] = None,
    skills: Optional[list[str]] = None,
    province: Optional[str] = None,
    country_code: Optional[str] = None,
    limit: int = 40,
) -> list[dict]:
    """Return talent rows matching any of the supplied certs/skills/location.

    Matching is OR-within-field, AND-across-field so a stricter brief narrows
    the pool. (The LLM does the final 'is this the right team' reasoning.)
    """
    db = _conn()
    try:
        sql = "SELECT * FROM talent WHERE available=1"
        params: list = []
        if country_code:
            sql += " AND country_code=?"
            params.append(country_code.upper())
        if province:
            sql += " AND province LIKE ?"
            params.append(f"%{province}%")
        sql += " ORDER BY available DESC, id ASC LIMIT ?"
        params.append(limit)
        rows = db.execute(sql, params).fetchall()
        out = [_row_to_dict(r) for r in rows]
    finally:
        db.close()

    # Post-filter on certs/skills (JSON columns — done in Python to stay portable).
    if certs or skills:
        want_certs = {c.lower() for c in (certs or [])}
        want_skills = {s.lower() for s in (skills or [])}
        filtered = []
        for t in out:
            raw_certs = _j(t["certs"])
            cert_pairs = raw_certs.items() if isinstance(raw_certs, dict) else {}
            have_certs = {str(k).lower() for k, _ in cert_pairs} | {
                str(v).lower() for _, v in cert_pairs if isinstance(v, bool) and v
            }
            have_skills = {str(s).lower() for s in _j(t["skills"])}
            hit_c = bool(want_certs & have_certs) if want_certs else False
            hit_s = bool(want_skills & have_skills) if want_skills else False
            if hit_c or hit_s:
                filtered.append(t)
        out = filtered or out  # if nothing matches, return the broad pool for context
    return out


def get_profile(tid: int) -> Optional[dict]:
    db = _conn()
    try:
        row = db.execute("SELECT * FROM talent WHERE id=?", (tid,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        db.close()


def add_talent(**fields) -> int:  # noqa: D401
    cols = ["name", "type", "country_code", "province", "skills", "certs",
            "languages", "rate_day", "available", "contact", "bio"]
    keys = [c for c in cols if c in fields]
    vals = [fields.get(c) for c in keys]
    db = _conn()
    try:
        cur = db.execute(
            f"INSERT INTO talent ({','.join(keys)}) VALUES ({','.join(['?']*len(keys))})",
            vals,
        )
        db.commit()
        return int(cur.lastrowid or 0)
    finally:
        db.close()


def _row_to_dict(r) -> dict:
    d = {k: r[k] for k in r.keys()}
    # Pretty-print the JSON-ish columns for the LLM prompt / API response.
    for col in ("skills", "certs", "languages"):
        d[col] = _j(d.get(col))
    return d


if __name__ == "__main__":
    print(f"talent rows: {talent_count()}")
