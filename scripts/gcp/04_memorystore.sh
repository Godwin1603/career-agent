#!/usr/bin/env bash
#
# 04_memorystore.sh
# Provisions a Memorystore Redis instance.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
REGION="${REGION:-us-central1}"
REDIS_NAME="career-agent-redis"
NETWORK="default"

echo "========================================="
echo "Provisioning Memorystore Redis: ${REDIS_NAME}"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
if gcloud redis instances describe "${REDIS_NAME}" --region="${REGION}" >/dev/null 2>&1; then
  echo "INFO: Redis instance ${REDIS_NAME} already exists. Skipping creation."
else
  echo "Creating High-Availability Redis instance (this takes about 5 minutes)..."
  # Standard HA tier provides automated failover to a replica across zones.
  gcloud redis instances create "${REDIS_NAME}" \
    --size=1 \
    --region="${REGION}" \
    --network="projects/${PROJECT_ID}/global/networks/${NETWORK}" \
    --tier=standard_ha \
    --redis-version=redis_7_0
fi

# Retrieve the IP and Port
REDIS_IP=$(gcloud redis instances describe "${REDIS_NAME}" --region="${REGION}" --format="value(host)")
REDIS_PORT=$(gcloud redis instances describe "${REDIS_NAME}" --region="${REGION}" --format="value(port)")

echo ""
echo "========================================="
echo "SUCCESS: Memorystore Redis HA provisioned successfully!"
echo "Redis IP   : ${REDIS_IP}"
echo "Redis Port : ${REDIS_PORT}"
echo "========================================="

# Save for Secret Manager
echo "REDIS_URL=redis://${REDIS_IP}:${REDIS_PORT}/0" > /tmp/career_agent_redis_url.txt
chmod 600 /tmp/career_agent_redis_url.txt
echo "INFO: Temporary credentials saved to /tmp/career_agent_redis_url.txt"
