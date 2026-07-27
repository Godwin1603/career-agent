#!/usr/bin/env bash
#
# 10_verify.sh
# Audits the entire infrastructure and validates Cloud Run service health.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="career-agent"
SA_NAME="career-agent-worker"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "========================================="
echo "Verifying Deployment & Infrastructure"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# Infrastructure Audit
# -----------------------------------------------------------------------------
echo "1. Checking IAM Service Account..."
if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  echo "ERROR: Service Account ${SA_EMAIL} missing."
  exit 1
fi

echo "2. Checking Cloud SQL Database..."
if ! gcloud sql instances describe "career-agent-db-instance" >/dev/null 2>&1; then
  echo "ERROR: Cloud SQL instance missing."
  exit 1
fi

echo "3. Checking Redis Cache..."
if ! gcloud redis instances describe "career-agent-redis" --region="${REGION}" >/dev/null 2>&1; then
  echo "ERROR: Redis instance missing."
  exit 1
fi

echo "4. Checking Cloud Storage..."
if ! gcloud storage ls "gs://career-agent-data-${PROJECT_ID}" >/dev/null 2>&1; then
  echo "ERROR: GCS Bucket missing."
  exit 1
fi

echo "5. Checking Cloud Tasks..."
if ! gcloud tasks queues describe "portal-application-q" --location="${REGION}" >/dev/null 2>&1; then
  echo "ERROR: Cloud Tasks queue missing."
  exit 1
fi

# -----------------------------------------------------------------------------
# Health Check with Retry Backoff
# -----------------------------------------------------------------------------
echo "6. Probing Cloud Run Application Health..."

# Retrieve Service URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format="value(status.url)")

if [[ -z "${SERVICE_URL}" ]]; then
  echo "ERROR: Could not retrieve Cloud Run service URL."
  exit 1
fi

echo "Target: ${SERVICE_URL}/health/ready"

MAX_RETRIES=10
RETRY_COUNT=0
HTTP_CODE=0
# To probe an authenticated Cloud Run service, we must attach an identity token.
# Note: The local user running this script must have 'roles/run.invoker'.
ID_TOKEN=$(gcloud auth print-identity-token 2>/dev/null || echo "")

if [[ -z "${ID_TOKEN}" ]]; then
  echo "WARNING: Could not generate identity token. Ensure you have gcloud auth logged in."
fi

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
  if [[ -n "${ID_TOKEN}" ]]; then
    HTTP_CODE=$(curl -s -o /tmp/health_response.json -w "%{http_code}" \
      -H "Authorization: Bearer ${ID_TOKEN}" \
      "${SERVICE_URL}/health/ready")
  else
    HTTP_CODE=$(curl -s -o /tmp/health_response.json -w "%{http_code}" "${SERVICE_URL}/health/ready")
  fi

  if [[ "${HTTP_CODE}" == "200" ]]; then
    echo "SUCCESS: Service is healthy and ready!"
    echo "Response Payload:"
    cat /tmp/health_response.json | jq . || cat /tmp/health_response.json
    echo ""
    break
  fi

  echo "Attempt $((RETRY_COUNT+1)) failed with HTTP ${HTTP_CODE}. Service might be cold-starting. Retrying in 10s..."
  sleep 10
  ((RETRY_COUNT++))
done

if [[ "${HTTP_CODE}" != "200" ]]; then
  echo "ERROR: Service failed to report healthy after ${MAX_RETRIES} attempts."
  if [[ -f /tmp/health_response.json ]]; then
    echo "Last Response Payload:"
    cat /tmp/health_response.json | jq . || cat /tmp/health_response.json
  fi
  echo "Please check Cloud Run logs for StartupValidator errors."
  exit 1
fi

echo "========================================="
echo "ALL SYSTEMS GO: Verification Complete!"
echo "========================================="
