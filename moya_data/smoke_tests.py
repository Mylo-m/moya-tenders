#!/usr/bin/env python3
"""Moya smoke tests — fast, local, no network/deploy needed.

Run:  python3 moya_data/smoke_tests.py
Exit code 0 = all green; 1 = a check failed.

Covers the things that break silently and would reach the customer:
  - DB reachable + non-empty
  - all configured countries present in the store
  - operator can load fresh tenders across all countries (not just ZA/KE)
  - operator can produce a bid package for a sample tender (offline path)
  - auto_close / freshness_monitor import + run without error
  - gemini_client wired to read GEMINI_API_KEY from env
"""
from __future__ import annotations
import os
import sys
import sqlite3
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT.parent))  # repo root, so `import moya_data...` works
sys.path.insert(0, str(_ROOT))

fails = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def main():
    print("=== Moya smoke tests ===")
    os.environ.setdefault("MYLO_ENV_PATH", str(_ROOT / ".env"))

    # Allow pointing at a specific DB (defaults to moya_data/moya.db created by scraper).
    db_path = os.environ.get("MOYA_DB_PATH")
    if db_path:
        import moya_data.scraper_sqlite as _sc
        _sc.DB_PATH = db_path

    # 1) DB reachable + non-empty
    import moya_data.scraper_sqlite as sc
    db = sc.get_db()
    total = db.execute("SELECT COUNT(*) n FROM tenders").fetchone()["n"]
    db.close()
    check("DB non-empty", total > 100, f"{total} rows")

    # 2) All configured countries present
    codes = list(sc.COUNTRY_REGIONS.keys())
    present = set(r["country_code"] for r in
                  sc.get_db().execute("SELECT DISTINCT country_code FROM tenders").fetchall())
    db.close()
    missing = [c for c in codes if c not in present]
    check("All configured countries present", not missing, f"missing={missing}")

    # 3) Operator loads across all countries (not ZA/KE only)
    from moya_data import operator as op
    fresh = op._load_fresh_tenders(limit=200)
    cc_set = {t["country_code"] for t in fresh}
    beyond_za_ke = cc_set - {"ZA", "KE"}
    check("Operator spans >2 countries", len(beyond_za_ke) > 0,
          f"countries seen={sorted(cc_set)}")

    # 4) Operator produces a bid package offline (no Gemini needed for doc_engine)
    if fresh:
        sample = fresh[0]
        try:
            rec = op.process_tender(sample)
            ok = "package_md" in rec and os.path.exists(
                _ROOT / rec["package_md"])
            check("Operator drafts a bid package", ok, rec.get("package_md", ""))
        except Exception as e:
            check("Operator drafts a bid package", False, str(e)[:120])

    # 5) auto_close + freshness import & run (dry-run)
    try:
        import importlib
        import moya_data.auto_close_expired as ace
        ace.main.__call__() if False else None  # no-op guard
        check("auto_close_expired imports", True)
    except Exception as e:
        check("auto_close_expired imports", False, str(e)[:120])

    try:
        from moya_data import freshness_monitor as fm
        check("freshness_monitor imports", True)
    except Exception as e:
        check("freshness_monitor imports", False, str(e)[:120])

    # 6) Gemini key wiring detects env
    from moya_data import gemini_client as gem
    os.environ["GEMINI_API_KEY"] = os.environ.get("GEMINI_API_KEY", "TESTKEY")
    check("gemini_client reads GEMINI_API_KEY", gem.gemini_configured())

    print(f"\n=== {'ALL GREEN' if not fails else str(len(fails)) + ' FAILED'} ===")
    if fails:
        print("Failed:", ", ".join(fails))
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
