"""
Moya — scheduled scraper orchestrator (the "agentic, async, no supervision" core).

Invoked by Cloud Scheduler every 6 hours:
  1. Pull the latest tender store from Cloud Storage (runs accumulate).
  2. Run the multi-country scraper -> populates moya.db.
  3. Push the updated store back to Cloud Storage (survives container restarts).

Locally (no GCS_BUCKET / no creds) it just runs the scraper against the local
sqlite file — safe for dev. Failures in the scrape are caught so the push of
whatever was saved still happens.
"""
from __future__ import annotations

import os
import sys
import json
import time
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from moya_data import gcs_sync  # noqa: E402


def run_cron() -> dict:
    t0 = time.time()
    pulled = gcs_sync.pull_db()  # no-op if GCS_BUCKET unset / offline

    scrape_error = None
    try:
        import scraper_sqlite as sc
        sc.run()
    except Exception as e:  # never let a scrape failure block the GCS push
        scrape_error = str(e)

    pushed = gcs_sync.push_db()  # no-op if unset / offline

    # Autonomous action: after scraping, the operator shreds fresh tenders and
    # auto-drafts bid packages with Gemini + doc_engine — no human in the loop.
    operator_summary = None
    operator_error = None
    try:
        from moya_data import operator as op
        operator_summary = op.run_operator()
    except Exception as e:  # operator failure must never block the scrape/push
        operator_error = str(e)

    return {
        "ok": scrape_error is None,
        "gcs_pulled": pulled,
        "gcs_pushed": pushed,
        "scrape_error": scrape_error,
        "operator_summary": operator_summary,
        "operator_error": operator_error,
        "seconds": round(time.time() - t0, 1),
        "time": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    print(json.dumps(run_cron(), indent=2))
