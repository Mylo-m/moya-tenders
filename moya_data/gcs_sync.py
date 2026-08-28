"""
Moya — Cloud Storage sync for the tender SQLite store (hackathon requirement #3:
a real Google Cloud data service). On Cloud Run the container filesystem is
ephemeral, so moya.db is hydrated from / persisted to a GCS bucket.

Locally (no GCS_BUCKET / no creds) every call is a no-op, so dev still works.
"""
from __future__ import annotations

import os
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "moya.db"


def _client():
    from google.cloud import storage
    return storage.Client()


def pull_db(bucket: str | None = None) -> bool:
    bucket = bucket or os.getenv("GCS_BUCKET")
    if not bucket:
        return False
    try:
        blob = _client().bucket(bucket).blob("moya.db")
        if blob.exists():
            blob.download_to_filename(str(DB_PATH))
            return True
    except Exception:
        pass
    return False


def push_db(bucket: str | None = None) -> bool:
    bucket = bucket or os.getenv("GCS_BUCKET")
    if not bucket or not DB_PATH.exists():
        return False
    try:
        _client().bucket(bucket).blob("moya.db").upload_from_filename(str(DB_PATH))
        return True
    except Exception:
        return False


def save_match(match: dict, bucket: str | None = None) -> bool:
    """Persist a generated consortium/match JSON to GCS (hackathon req #3).

    Stored under matches/<tender_id>_<timestamp>.json. No-op (returns False)
    when GCS_BUCKET is unset, so local runs stay clean.
    """
    bucket = bucket or os.getenv("GCS_BUCKET")
    if not bucket:
        return False
    try:
        import json as _json
        from datetime import datetime, timezone
        tid = match.get("tender_id") or "inline"
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        blob = _client().bucket(bucket).blob(f"matches/{tid}_{ts}.json")
        blob.upload_from_string(
            _json.dumps(match, ensure_ascii=False, indent=2),
            content_type="application/json",
        )
        return True
    except Exception:
        return False
