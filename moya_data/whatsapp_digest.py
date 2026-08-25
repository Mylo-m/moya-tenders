#!/usr/bin/env python3
"""
Moya — Daily WhatsApp Digest Sender
For every user with whatsapp_digest=1, build a short summary of their scoped
tenders (new + closing soon) and push it via the MY-LO business WhatsApp number.

Delivery: uses the configured WhatsApp channel (e.g. WhatsApp Business API /
Twilio / a local bridge). Credentials are read from the environment, never
hard-coded. Every send is recorded in the DB (moya_whatsapp_log) for POPIA.

Run daily at 08:00 via the Hermes scheduled job.
"""
import os
import sqlite3
import json
import datetime
import requests

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'moya.db')

# WhatsApp delivery config (back-burner: real provider wired on user confirmation)
WA_TOKEN = os.environ.get('MoyaWA_TOKEN', '')
WA_FROM = os.environ.get('MoyaWA_FROM', '')          # MY-LO business number / sender id
WA_API_URL = os.environ.get('MoyaWA_API_URL', '')    # provider endpoint

def get_db():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db

def ensure_log(db):
    db.execute("""CREATE TABLE IF NOT EXISTS moya_whatsapp_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        to_number TEXT,
        message TEXT,
        status TEXT,
        sent_at TEXT DEFAULT (datetime('now'))
    )""")
    db.commit()

def build_message(user, tenders, closing):
    name = (user['name'] or 'there').split()[0]
    lines = [f"Good morning {name}! \U0001F5E3 Your Moya digest ({datetime.date.today():%d %b %Y})"]
    if tenders:
        lines.append(f"\n\U0001F4E5 {len(tenders)} fresh tender(s) in your sectors:")
        for t in tenders[:8]:
            lines.append(f"• {t['title'][:90]}")
            if t['closing_date']:
                lines.append(f"   closes {t['closing_date']}")
    if closing:
        lines.append(f"\n\u23F0 {len(closing)} closing within 7 days:")
        for t in closing[:5]:
            lines.append(f"• {t['title'][:80]} — {t['closing_date']}")
    lines.append("\nView all: https://www.mylo.co.za/moya_data/dashboard.php")
    return "\n".join(lines)

def send_whatsapp(to, text):
    """Send via configured provider. Returns (ok, detail)."""
    if not (WA_TOKEN and WA_FROM and WA_API_URL):
        # Back-burner: provider not configured yet. Record as 'pending'.
        return False, 'provider_not_configured'
    try:
        r = requests.post(WA_API_URL, json={
            'token': WA_TOKEN, 'from': WA_FROM, 'to': to, 'message': text
        }, timeout=20)
        return r.status_code == 200, f"HTTP {r.status_code}"
    except Exception as e:
        return False, str(e)

def run():
    db = get_db()
    ensure_log(db)
    cur = db.execute("SELECT * FROM users WHERE whatsapp_digest = 1")
    users = cur.fetchall()
    print(f"WhatsApp digest: {len(users)} subscriber(s)")
    for u in users:
        allowed = []
        if u['base_sector']: allowed.append(u['base_sector'])
        if u['extra_sectors']:
            allowed += [s.strip() for s in u['extra_sectors'].split(',') if s.strip()]
        if not allowed:
            continue
        ph = ",".join(["?"] * len(allowed))
        new = db.execute(
            f"SELECT * FROM tenders WHERE sector IN ({ph}) AND date(created_at)=date('now') ORDER BY closing_date ASC",
            allowed).fetchall()
        closing = db.execute(
            f"SELECT * FROM tenders WHERE sector IN ({ph}) AND status='open' AND closing_date IS NOT NULL "
            f"AND date(closing_date) BETWEEN date('now') AND date('now','+7 days') ORDER BY closing_date ASC",
            allowed).fetchall()
        to = u['phone'] or ''
        msg = build_message(u, new, closing)
        ok, detail = send_whatsapp(to, msg)
        status = 'sent' if ok else ('pending' if detail == 'provider_not_configured' else 'failed')
        db.execute("INSERT INTO moya_whatsapp_log (user_id, to_number, message, status) VALUES (?,?,?,?)",
                   (u['id'], to, msg, status))
        db.commit()
        print(f"  user {u['id']} ({to}): {status} — {detail}")
    db.close()

if __name__ == '__main__':
    run()
