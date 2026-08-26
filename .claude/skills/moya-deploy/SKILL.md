---
name: moya-deploy
description: "Deploy or update the Moya live surface (FTP dashboard/DB to mylo.co.za, or Cloud Run backend). Use before any live change. Encodes the reversible deploy ritual: backup-first, verify, never deploy without explicit user confirm."
version: 1.0.0
author: MY-LO
license: MIT
---
# Moya Deploy Skill

## HARD RULE
**Never deploy to live without explicit user confirmation.** The user has
stated this twice. Dashboard/DB changes stay local until they say "go".

## Live topology (verify before writing)
- Dashboard: `public_html/moya_data/dashboard.php` (reads `moya.db` via `moya.php`).
- TWO live DB copies exist: `public_html/moya.db` (root) and
  `public_html/moya_data/moya.db`. Know which is source of truth before writing.
- FTP: host `213.133.106.131`, user `myloxy`, pass from `C:\Users\ordio\.env`
  (`FTP_PASS`). Use `ftplib` (lftp not installed). Switch to binary mode
  (`ftp.voidcmd('TYPE I')`) before `size`/`retrbinary`/`storbinary`.

## Reversible FTP deploy ritual
1. `cwd` to the target dir.
2. **Backup first**: `ftp.rename("file.php", f"file.php.bak_<ts>")` (ts = YYYYMMDD_HHMMSS).
3. Upload: `ftp.storbinary("STOR file.php", open(local,"rb"))`.
4. **Verify**: re-download or fetch the live endpoint; confirm expected bytes
   / `ok:true`. Never assume success.
5. Report what changed + the backup filename so it's restorable in one command.

## Cloud Run deploy (hackathon requirement — NOT done yet)
- Prereq: GCP project + billing + `gcloud` installed + `GEMINI_API_KEY` in
  Secret Manager.
- Script: `bash deploy_cloudrun.sh` (enables APIs, creates GCS bucket, deploys
  `moya_api/server.py`, wires Cloud Scheduler 6h cron).
- Produces a `*.run.app` URL = proof of "deployed on Google Cloud".
- Do NOT run until the user provides the GCP key + says deploy.

## Verification checklist
- [ ] Backup created before overwrite
- [ ] Upload succeeded (byte count matches)
- [ ] Live endpoint returns `ok:true` with expected data
- [ ] Dashboard renders (not "Error loading tenders")
- [ ] User confirmed the deploy
