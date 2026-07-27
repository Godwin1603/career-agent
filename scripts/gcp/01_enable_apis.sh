#!/usr/bin/env bash
#
# 01_enable_apis.sh
# Enables all required Google Cloud APIs for the Career Agent project.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"

echo "========================================="
echo "Enabling APIs for project: ${PROJECT_ID}"
echo "========================================="

# Validate gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo "ERROR: gcloud CLI could not be found. Please install Google Cloud SDK."
    exit 1
fi

# Validate authentication
if ! gcloud auth print-access-token &> /dev/null; then
    echo "ERROR: You are not authenticated. Please run 'gcloud auth login'."
    exit 1
fi

# Ensure gcloud is configured for the right project
if ! gcloud config set project "${PROJECT_ID}"; then
    echo "ERROR: Failed to set project ${PROJECT_ID}. Verify the Project ID and your permissions."
    exit 1
fi

# Verify Billing is enabled
BILLING_ENABLED=$(gcloud alpha billing projects describe "${PROJECT_ID}" --format="value(billingEnabled)" 2>/dev/null || echo "false")
if [[ "${BILLING_ENABLED}" != "True" && "${BILLING_ENABLED}" != "true" ]]; then
    echo "ERROR: Billing is not enabled for project ${PROJECT_ID}. Please enable billing first."
    exit 1
fi

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
APIS=(
  "compute.googleapis.com"              # Required for networking (VPC)
  "iam.googleapis.com"                  # Required for service accounts
  "cloudresourcemanager.googleapis.com" # Required for IAM policies
  "sqladmin.googleapis.com"             # Required for Cloud SQL
  "redis.googleapis.com"                # Required for Memorystore Redis
  "secretmanager.googleapis.com"        # Required for Secret Manager
  "cloudtasks.googleapis.com"           # Required for Cloud Tasks
  "aiplatform.googleapis.com"           # Required for Vertex AI (Gemini)
  "artifactregistry.googleapis.com"     # Required to store Docker images
  "cloudbuild.googleapis.com"           # Required to build Docker images
  "run.googleapis.com"                  # Required for Cloud Run
  "vpcaccess.googleapis.com"            # Required for Serverless VPC Access
  "servicedirectory.googleapis.com"     # Required for Cloud Run internal networking
)

echo "Enabling the following APIs (this may take a few minutes)..."
for api in "${APIS[@]}"; do
  echo " - ${api}"
done

# Enable all APIs in one command for efficiency
gcloud services enable "${APIS[@]}"

echo "========================================="
echo "SUCCESS: APIs enabled successfully!"
echo "========================================="
