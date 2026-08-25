#!/usr/bin/env bash
# Deploy MY-LO Moya to Google Cloud Run (the hackathon "proof of deployment").
#
# PREREQUISITES (one-time, on your machine):
#   1. gcloud installed:  https://cloud.google.com/sdk/docs/install
#   2. Authenticate:      gcloud auth login
#   3. Set project:       gcloud config set project <YOUR_GCP_PROJECT_ID>
#   4. Enable APIs:       gcloud services enable run.googleapis.com cloudbuild.googleapis.com
#   5. (Optional) Gemini key in Secret Manager:
#        gcloud secrets create gemini-api-key --data-file=<(printf '%s' "$GEMINI_API_KEY")
#
# Then run:  bash deploy_cloudrun.sh
set -euo pipefail

SERVICE="moya-tender-desk"
REGION="${REGION:-europe-west1}"      # closest to ZA latency; change if needed
PROJECT="$(gcloud config get-value project)"

echo ">> Deploying $SERVICE to Cloud Run in $PROJECT / $REGION"

if gcloud secrets describe gemini-api-key >/dev/null 2>&1; then
  GEMINI_ARG="--set-secrets=GEMINI_API_KEY=gemini-api-key:latest"
else
  echo "   (no gemini-api-key secret found — deploying without Gemini; /api/shred will return 503 until you add it)"
  GEMINI_ARG=""
fi

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --timeout 120 \
  --cpu 1 \
  --memory 512Mi \
  $GEMINI_ARG

URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
echo ""
echo ">> LIVE URL: $URL"
echo ">> Health:   $URL/api/health"
echo ">> Demo:     $URL/api/tenders  |  $URL/api/stats"
echo ""
echo "Paste $URL into the hackathon demo video + README as your Cloud Run proof."
