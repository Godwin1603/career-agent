#!/usr/bin/env bash
#
# 06_cloud_tasks.sh
# Provisions Cloud Tasks Queues with production rate limits.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
REGION="${REGION:-us-central1}"

QUEUES=(
  "job-enrichment-q"
  "portal-application-q"
  "form-application-q"
  "email-application-q"
  "notification-q"
)

echo "========================================="
echo "Provisioning Cloud Tasks Queues"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
for QUEUE in "${QUEUES[@]}"; do
  if gcloud tasks queues describe "${QUEUE}" --location="${REGION}" >/dev/null 2>&1; then
    echo "INFO: Queue ${QUEUE} already exists. Updating rate limits..."
    # Update limits if it already exists
    # max-attempts=3 and max-concurrent-dispatches=5 are production-safe defaults for browser automation
    gcloud tasks queues update "${QUEUE}" \
      --location="${REGION}" \
      --max-concurrent-dispatches=5 \
      --max-attempts=3 \
      --max-dispatches-per-second=2.0
  else
    echo "Creating queue ${QUEUE} in ${REGION}..."
    gcloud tasks queues create "${QUEUE}" \
      --location="${REGION}" \
      --max-concurrent-dispatches=5 \
      --max-attempts=3 \
      --max-dispatches-per-second=2.0
  fi
done

echo "========================================="
echo "SUCCESS: Cloud Tasks provisioned successfully!"
echo "========================================="
