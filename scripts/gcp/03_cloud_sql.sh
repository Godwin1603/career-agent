#!/usr/bin/env bash
#
# 03_cloud_sql.sh
# Provisions a Cloud SQL PostgreSQL instance and database.
# Ensures the instance uses a private IP to avoid public exposure.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
REGION="${REGION:-us-central1}"
INSTANCE_NAME="career-agent-db-instance"
DB_NAME="career_agent"
DB_USER="career_user"
NETWORK="default"

echo "========================================="
echo "Provisioning Cloud SQL: ${INSTANCE_NAME}"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
# 1. Setup Private Services Access (Required for private IP Cloud SQL/Redis)
echo "Ensuring Private Services Access is configured on network: ${NETWORK}..."
if ! gcloud compute addresses describe google-managed-services-${NETWORK} --global >/dev/null 2>&1; then
  echo "Allocating IP range for private services..."
  gcloud compute addresses create google-managed-services-${NETWORK} \
    --global \
    --purpose=VPC_PEERING \
    --prefix-length=20 \
    --network="projects/${PROJECT_ID}/global/networks/${NETWORK}"
else
  echo "INFO: Private IP range already allocated."
fi

if ! gcloud services vpc-peerings list --network=${NETWORK} | grep -q "servicenetworking-googleapis-com"; then
  echo "Creating VPC peering connection for private services..."
  gcloud services vpc-peerings connect \
    --service=servicenetworking.googleapis.com \
    --ranges=google-managed-services-${NETWORK} \
    --network=${NETWORK} \
    --project=${PROJECT_ID}
else
  echo "INFO: VPC peering already established."
fi

# 2. Provision Cloud SQL Instance
if gcloud sql instances describe "${INSTANCE_NAME}" >/dev/null 2>&1; then
  echo "INFO: Cloud SQL instance ${INSTANCE_NAME} already exists. Skipping creation."
else
  echo "Creating PostgreSQL 15 instance (this takes 5-10 minutes)..."
  gcloud sql instances create "${INSTANCE_NAME}" \
    --database-version=POSTGRES_15 \
    --tier=db-f1-micro \
    --region="${REGION}" \
    --network="${NETWORK}" \
    --no-assign-ip \
    --storage-type=SSD \
    --storage-size=10GB \
    --storage-auto-increase \
    --require-ssl \
    --enable-point-in-time-recovery \
    --backup-start-time=02:00 \
    --availability-type=ZONAL
fi

# 3. Create Database
if gcloud sql databases describe "${DB_NAME}" --instance="${INSTANCE_NAME}" >/dev/null 2>&1; then
  echo "INFO: Database ${DB_NAME} already exists."
else
  echo "Creating database ${DB_NAME}..."
  gcloud sql databases create "${DB_NAME}" --instance="${INSTANCE_NAME}"
fi

# 4. Create User (Generate strong random password via OpenSSL)
echo "Managing database user: ${DB_USER}..."
# Use openssl for robust password generation. Produces 32 characters of hex (alphanumeric, safe for URLs).
DB_PASS=$(openssl rand -hex 16)

if gcloud sql users describe "${DB_USER}" --instance="${INSTANCE_NAME}" >/dev/null 2>&1; then
  echo "User ${DB_USER} exists. Updating password..."
  gcloud sql users set-password "${DB_USER}" \
    --instance="${INSTANCE_NAME}" \
    --password="${DB_PASS}"
else
  echo "Creating user ${DB_USER}..."
  gcloud sql users create "${DB_USER}" \
    --instance="${INSTANCE_NAME}" \
    --password="${DB_PASS}"
fi

# Retrieve the Private IP of the instance
DB_IP=$(gcloud sql instances describe "${INSTANCE_NAME}" --format="value(ipAddresses[0].ipAddress)")
CONNECTION_NAME="${PROJECT_ID}:${REGION}:${INSTANCE_NAME}"

echo ""
echo "========================================="
echo "SUCCESS: Cloud SQL provisioned successfully!"
echo "Instance IP : ${DB_IP}"
echo "DB User     : ${DB_USER}"
echo "DB Password : (hidden, will be saved to Secret Manager)"
echo "Connection  : ${CONNECTION_NAME}"
echo "========================================="

# Save credentials to a temporary file for 08_secret_manager.sh
# Cloud Run native Cloud SQL proxy using Unix sockets is the standard secure way to bypass --require-ssl handshake complexity.
echo "DATABASE_URL=postgresql+asyncpg://${DB_USER}:${DB_PASS}@/career_agent?host=/cloudsql/${CONNECTION_NAME}" > /tmp/career_agent_db_url.txt
chmod 600 /tmp/career_agent_db_url.txt
echo "INFO: Temporary credentials saved to /tmp/career_agent_db_url.txt"
