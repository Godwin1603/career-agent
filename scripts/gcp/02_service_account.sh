#!/usr/bin/env bash
#
# 02_service_account.sh
# Creates a dedicated Service Account for Cloud Run with least privilege.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
SA_NAME="career-agent-worker"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
DISPLAY_NAME="Career Agent Cloud Run Worker"

echo "========================================="
echo "Configuring Service Account: ${SA_NAME}"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
# Check if Service Account already exists
if gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  echo "INFO: Service account ${SA_EMAIL} already exists. Skipping creation."
else
  echo "Creating service account ${SA_EMAIL}..."
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="${DISPLAY_NAME}"
fi

# Required IAM Roles for the worker (Least Privilege)
ROLES=(
  "roles/cloudsql.client"                # Allows connection to Cloud SQL
  "roles/redis.editor"                   # Allows connection to Memorystore
  "roles/secretmanager.secretAccessor"   # Allows reading from Secret Manager
  "roles/cloudtasks.enqueuer"            # Allows pushing to Cloud Tasks
  "roles/aiplatform.user"                # Allows using Vertex AI (Gemini)
  "roles/storage.objectAdmin"            # Allows uploading files to GCS
  "roles/run.invoker"                    # Allows Cloud Tasks OIDC token to invoke this Cloud Run service
)

echo "Assigning strict IAM roles..."
for role in "${ROLES[@]}"; do
  echo " - Binding ${role}"
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${role}" \
    --condition=None \
    >/dev/null
done

echo "========================================="
echo "SUCCESS: Service Account configured successfully!"
echo "Service Account Email: ${SA_EMAIL}"
echo "========================================="
