#!/usr/bin/env bash
# Deploy MY-LO Moya to Google Cloud Run (hackathon "proof of deployment") +
# wire Cloud Storage (real GCP data store) + Gemini via Secret Manager.
#
# PREREQUISITES (your one-time manual steps — only you can do these):
#   1. Create a GCP project: https://console.cloud.google.com/  (free trial, no credits needed)
#   2. Install gcloud:       https://cloud.google.com/sdk/docs/install
#   3. gcloud auth login     # opens browser, approve, select that project
#   4. gcloud config set project <YOUR_PROJECT_ID>
#   5. (recommended) put the Gemini key in Secret Manager:
#      echo -n "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=-
#
# Then run:  bash deploy_cloudrun.sh
set -euo pipefail

SERVICE="moya-tender-desk"
REGION="${REGION:-europe-west1}"   # change to africa-south1 if GCP enables it for you; europe-west1 is free-tier safe
PROJECT="$(gcloud config get-value project)"
BUCKET="${GCS_BUCKET:-moya-tenders-data}"

echo ">> Project: $PROJECT   Region: $REGION"

echo ">> Enabling APIs..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com storage.googleapis.com

echo ">> Creating GCS bucket gs://$BUCKET (real cloud data store)..."
gcloud storage buckets create "gs://$BUCKET" --location="$REGION" \
  --uniform-bucket-level-access 2>/dev/null || echo "   (bucket exists — skipping)"

echo ">> Loading GEMINI_API_KEY from .env ..."
KEY="$(grep -E '^GEMINI_API_KEY=' .env | head -1 | cut -d= -f2-)"
if [ -z "$KEY" ]; then echo "ERR: no GEMINI_API_KEY in .env"; exit 1; fi

if ! gcloud secrets describe gemini-api-key >/dev/null 2>&1; then
  echo ">> Creating Secret Manager entry (key stays out of image)..."
  printf '%s' "$KEY" | gcloud secrets create gemini-api-key --data-file=-
fi

echo ">> Generating CRON_SECRET + deploying (timeout 600s for the scraper job)..."
CRON_SECRET="$(openssl rand -hex 16)"
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --timeout 600 \
  --cpu 1 \
  --memory 512Mi \
  --set-secrets=GEMINI_API_KEY=gemini-api-key:latest \
  --set-env-vars=GCS_BUCKET="$BUCKET",CRON_SECRET="$CRON_SECRET"

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"

echo ">> Creating Cloud Scheduler job (every 6h, Africa/Johannesburg)..."
gcloud scheduler jobs delete moya-scrape --location="$REGION" --quiet 2>/dev/null || true
gcloud scheduler jobs create http moya-scrape \
  --location="$REGION" \
  --schedule="0 */6 * * *" \
  --uri="$URL/api/cron-scrape" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --body="{\"secret\":\"$CRON_SECRET\"}" \
  --time-zone="Africa/Johannesburg" \
  --attempt-deadline=600s

echo ""
echo ">> LIVE URL: $URL"
echo ">> Health:   $URL/api/health"
echo ">> Tenders:  $URL/api/tenders"
echo ">> Shred:    POST $URL/api/shred  {\"text\":\"...\"}"
echo ">> 6h cron:  gcloud scheduler jobs describe moya-scrape --location=$REGION"
echo ""
echo "Paste $URL into the hackathon demo video + README as Cloud Run proof."
