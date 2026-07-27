#!/usr/bin/env bash
#
# 05_cloud_storage.sh
# Provisions a Google Cloud Storage Bucket.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
REGION="${REGION:-us-central1}"
BUCKET_NAME="career-agent-data-${PROJECT_ID}"

echo "========================================="
echo "Provisioning Cloud Storage: ${BUCKET_NAME}"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
if gcloud storage ls "gs://${BUCKET_NAME}" >/dev/null 2>&1; then
  echo "INFO: Bucket gs://${BUCKET_NAME} already exists. Skipping creation."
else
  echo "Creating bucket gs://${BUCKET_NAME} in ${REGION}..."
  # Uniform bucket-level access is highly recommended for security.
  gcloud storage buckets create "gs://${BUCKET_NAME}" \
    --location="${REGION}" \
    --uniform-bucket-level-access

  # Object Versioning protects against accidental overwrites or deletes of resumes/artifacts.
  # Enable versioning for production safety.
  echo "Enabling Object Versioning..."
  gcloud storage buckets update "gs://${BUCKET_NAME}" --versioning
fi

echo "========================================="
echo "SUCCESS: Cloud Storage provisioned successfully!"
echo "Bucket Name: ${BUCKET_NAME}"
echo "========================================="
