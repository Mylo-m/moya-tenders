#!/usr/bin/env python3
"""Auto-close tenders whose closing_date is in the past.

Dead opportunities must not sit in the live 'open' feed forever. This flips
them to status='closed' (idempotent: only touches currently-open rows with a
past closing_date). Safe to run on every cron tick.

Usage:
  python3 auto_close_expired.py           # dry-run (prints what would change)
  python3 auto_close_expired.py --apply   # actually update
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from datetime import datetime

_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moya.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually update rows (default dry-run)")
    args = ap.parse_args()

    db = sqlite3.connect(_DB)
    db.row_factory = sqlite3.Row
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = db.execute(
        "SELECT id, title, country_code, closing_date FROM tenders "
        "WHERE status='open' AND closing_date IS NOT NULL AND closing_date != '' "
        "AND closing_date < ? ORDER BY closing_date ASC",
        (now,),
    ).fetchall()

    print(f"[auto-close] {len(rows)} open tender(s) past closing date (now={now})")
    for r in rows:
        print(f"  -> [{r['country_code']}] id={r['id']} closes {r['closing_date']}: {r['title'][:60]}")
        if args.apply:
            db.execute("UPDATE tenders SET status='closed' WHERE id=?", (r["id"],))
    if args.apply:
        db.commit()
        print(f"[auto-close] applied: {len(rows)} row(s) set to closed.")
    else:
        print("[auto-close] DRY-RUN — no changes made. Use --apply to update.")
    db.close()


if __name__ == "__main__":
    main()
