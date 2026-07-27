#!/usr/bin/env bash
#
# 09_cloud_run.sh
# Builds and deploys the Career Agent to Cloud Run securely.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="career-agent"
REPO_NAME="career-agent-repo"
SA_EMAIL="career-agent-worker@${PROJECT_ID}.iam.gserviceaccount.com"
NETWORK="default"

echo "========================================="
echo "Deploying Cloud Run Service: ${SERVICE_NAME}"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# 1. Determine immutable image tag
# Use Git commit SHA if available, fallback to timestamp if not in a git repo.
COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d-%H%M%S)
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/${SERVICE_NAME}:${COMMIT_SHA}"

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
echo "Building Docker image with tag: ${COMMIT_SHA}..."
gcloud builds submit --tag "${IMAGE_URI}" .

# 2. Deploy to Cloud Run
# 
# Key security configurations:
# - Mounts secrets natively from Secret Manager.
# - Attaches the custom least-privilege service account.
# - Connects to the default VPC using Direct VPC Egress for private DB/Redis access.
# - Limits max-instances to 10 to prevent DB connection exhaustion.
# - Adds the Cloud SQL proxy sidecar for secure SSL unix socket connection.
echo "Deploying to Cloud Run securely (no unauthenticated access)..."
gcloud run deploy "${SERVICE_NAME}" \
  --image="${IMAGE_URI}" \
  --region="${REGION}" \
  --service-account="${SA_EMAIL}" \
  --network="${NETWORK}" \
  --subnet="default" \
  --vpc-egress="private-ranges-only" \
  --no-allow-unauthenticated \
  --max-instances=10 \
  --cpu=1 \
  --memory=512Mi \
  --add-cloudsql-instances="${PROJECT_ID}:${REGION}:career-agent-db-instance" \
  --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID},\
CLOUD_TASKS_LOCATION=${REGION},\
GCS_BUCKET_NAME=career-agent-data-${PROJECT_ID},\
CLOUD_TASKS_QUEUE_JOB_ENRICHMENT=job-enrichment-q,\
CLOUD_TASKS_QUEUE_PORTAL_APPLICATION=portal-application-q,\
CLOUD_TASKS_QUEUE_FORM_APPLICATION=form-application-q,\
CLOUD_TASKS_QUEUE_EMAIL_APPLICATION=email-application-q,\
CLOUD_TASKS_QUEUE_NOTIFICATION=notification-q,\
VERTEX_AI_LOCATION=${REGION},\
GEMINI_MODEL=gemini-2.5-flash,\
GMAIL_SENDER_ADDRESS=candidate@example.com" \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest,\
REDIS_URL=REDIS_URL:latest,\
TELEGRAM_API_ID=TELEGRAM_API_ID:latest,\
TELEGRAM_API_HASH=TELEGRAM_API_HASH:latest,\
TELEGRAM_SESSION_STRING=TELEGRAM_SESSION_STRING:latest,\
GMAIL_OAUTH_CLIENT_ID=GMAIL_OAUTH_CLIENT_ID:latest,\
GMAIL_OAUTH_CLIENT_SECRET=GMAIL_OAUTH_CLIENT_SECRET:latest,\
GMAIL_OAUTH_REFRESH_TOKEN=GMAIL_OAUTH_REFRESH_TOKEN:latest"

# 3. Retrieve the deployed URL
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format="value(status.url)")

# 4. Update the service with its own URL so it knows where to send Cloud Tasks
echo "Updating Cloud Run service with its own URL (${SERVICE_URL})..."
gcloud run services update "${SERVICE_NAME}" \
  --region="${REGION}" \
  --set-env-vars="CLOUD_RUN_SERVICE_URL=${SERVICE_URL}"

echo "========================================="
echo "SUCCESS: Cloud Run deployed securely!"
echo "Service URL: ${SERVICE_URL}"
echo "Image Tag  : ${COMMIT_SHA}"
echo "========================================="
