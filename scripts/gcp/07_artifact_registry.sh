#!/usr/bin/env bash
#
# 07_artifact_registry.sh
# Provisions an Artifact Registry repository for Docker images.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
REGION="${REGION:-us-central1}"
REPO_NAME="career-agent-repo"

echo "========================================="
echo "Provisioning Artifact Registry: ${REPO_NAME}"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
if gcloud artifacts repositories describe "${REPO_NAME}" --location="${REGION}" >/dev/null 2>&1; then
  echo "INFO: Repository ${REPO_NAME} already exists. Skipping creation."
else
  echo "Creating repository ${REPO_NAME} in ${REGION}..."
  gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="Docker repository for Career Agent"
fi

echo "========================================="
echo "SUCCESS: Artifact Registry provisioned successfully!"
echo "Repository Path: ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}"
echo "========================================="
