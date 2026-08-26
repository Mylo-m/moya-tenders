#!/usr/bin/env python3
"""Moya production watchdog — daily chief-of-staff digest (Ryan Carson pattern).

Summarizes yesterday's important activity: new tenders per country + operator
output, with links back to the dashboard. Dry-run by default (prints only).
Use --arm to send to Telegram.

This is the "what happened yesterday that matters" report a founder reads each
morning — not just a new-tender ping (that's moya_watchdog.py).
"""
import argparse, os, sqlite3
from datetime import datetime, timedelta

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "moya.db")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="store_true")
    args = ap.parse_args()
    db = sqlite3.connect(DB); db.row_factory = sqlite3.Row
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT country_code, COUNT(*) n FROM tenders "
        "WHERE created_at >= ? AND status='open' GROUP BY country_code ORDER BY n DESC",
        (yesterday,)).fetchall()
    total = sum(r["n"] for r in rows)
    lines = [f"📊 Moya daily digest ({yesterday})", f"🔢 {total} new open tender(s)"]
    for r in rows:
        lines.append(f"  • {r['country_code']}: {r['n']} new")
    if not rows:
        lines.append("  (quiet day — no new tenders)")
    lines.append("View: https://mylo.co.za/moya_data/dashboard.php")
    msg = "\n".join(lines)
    print(msg)
    if args.arm:
        tok = os.getenv("MYLO_TG_BOT_TOKEN"); chat = os.getenv("MYLO_TG_CHAT_ID")
        if tok and chat:
            import requests
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": msg}, timeout=20)
            print("[watchdog] sent")
        else:
            print("[watchdog] no Telegram creds — not sent")
    db.close()

if __name__ == "__main__":
    main()
