#!/usr/bin/env bash
#
# Moya — Sync local SQLite DB to the live host via FTP.
# Source of truth = this machine's moya_data/moya.db.
# Live host serves it (PHP dashboard); it does NOT scrape (shared-host limits).
#
# Usage:  bash sync_tenders.sh
# Safe: backs up the live DB (rename) before overwrite.

set -euo pipefail

# --- config ---
HOST="213.133.106.131"
USER="myloxy"
REMOTE_DIR="/public_html/moya_data"
LOCAL_DB="$(cd "$(dirname "$0")" && pwd)/moya.db"
STAMP="$(date +%Y%m%d_%H%M%S)"

# FTP password from env or .env
if [ -z "${FTP_PASS:-}" ]; then
  FTP_PASS="$(grep '^FTP_PASS=' /mnt/c/Users/ordio/.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")"
fi

# --- backup live DB (rename) via FTP ---
BACKUP_CMD="rename moya.db moya.db.bak_${STAMP}"
echo "Backing up live DB..."
echo -e "user ${USER} ${FTP_PASS}\nbinary\ncd ${REMOTE_DIR}\n${BACKUP_CMD}\nbye" | curl -s --connect-timeout 20 --ftp-pasv --netrc-optional "ftp://${HOST}/" >/dev/null 2>&1 || true

# --- upload the local DB ---
echo "Uploading local DB ($(du -h "$LOCAL_DB" | cut -f1))..."
curl -s --connect-timeout 60 --ftp-pasv -T "$LOCAL_DB" "ftp://${USER}:${FTP_PASS}@${HOST}${REMOTE_DIR}/moya.db"
echo "Done. Live DB synced at ${STAMP}."
