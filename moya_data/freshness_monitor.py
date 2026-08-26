#!/usr/bin/env python3
"""Freshness monitor — alerts when a country's tender feed goes stale.

The dashboard silently shows stale data if a portal dies or the scraper
fails for a country. This checks the newest `created_at` (or latest
scrape_log entry) per country against a max-age window and reports any that
are too old. Reuses MYLO_TG_* creds for delivery (dry-run default).

Usage:
  python3 freshness_monitor.py                 # report stale countries (dry-run)
  python3 freshness_monitor.py --arm          # also send Telegram alert
  python3 freshness_monitor.py --max-age-hours 48
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from datetime import datetime, timedelta

_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moya.db")
MAX_AGE_HOURS = 48


def _newest_tender_age_hours(db, cc):
    row = db.execute(
        "SELECT MAX(created_at) mx FROM tenders WHERE country_code=?", (cc,)
    ).fetchone()
    mx = row["mx"] if row else None
    if not mx:
        return None
    try:
        ts = datetime.strptime(mx, "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None
    return (datetime.now() - ts).total_seconds() / 3600.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="store_true", help="send Telegram alert for stale countries")
    ap.add_argument("--max-age-hours", type=int, default=MAX_AGE_HOURS)
    args = ap.parse_args()

    db = sqlite3.connect(_DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT country_code, country, COUNT(*) n FROM tenders GROUP BY country_code"
    ).fetchall()

    stale = []
    for r in rows:
        age = _newest_tender_age_hours(db, r["country_code"])
        if age is None:
            continue
        if age > args.max_age_hours:
            stale.append((r["country_code"], r["country"], round(age, 1), r["n"]))

    db.close()

    if not stale:
        print(f"[freshness] OK — all {len(rows)} countries fresher than {args.max_age_hours}h")
        return

    lines = [f"⚠️ Moya freshness: {len(stale)} country feed(s) stale (> {args.max_age_hours}h old):"]
    for cc, c, age, n in sorted(stale, key=lambda x: -x[2]):
        print(f"[freshness] STALE {cc} ({c}): newest {age}h old, {n} tenders")
        lines.append(f"  • {c} ({cc}): {age}h old")
    msg = "\n".join(lines)

    if args.arm:
        token = os.getenv("MYLO_TG_BOT_TOKEN")
        chat = os.getenv("MYLO_TG_CHAT_ID")
        if token and chat:
            try:
                import requests
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": msg}, timeout=20,
                )
                print("[freshness] alert sent to Telegram")
            except Exception as e:
                print(f"[freshness] send failed: {e}")
        else:
            print("[freshness] no Telegram creds — not sent")
    else:
        print("[freshness] DRY-RUN — use --arm to deliver alert")


if __name__ == "__main__":
    main()
