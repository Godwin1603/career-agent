#!/usr/bin/env bash
#
# 08_secret_manager.sh
# Provisions secrets in Google Secret Manager.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
gcloud config set project "${PROJECT_ID}"

echo "========================================="
echo "Provisioning Secret Manager Secrets"
echo "========================================="

# Helper function to create or update a secret
create_secret() {
  local name=$1
  local value=$2

  if gcloud secrets describe "${name}" >/dev/null 2>&1; then
    echo "INFO: Secret ${name} already exists. Adding new version..."
  else
    echo "Creating secret ${name}..."
    gcloud secrets create "${name}" --replication-policy="automatic"
  fi

  echo -n "${value}" | gcloud secrets versions add "${name}" --data-file=-
  echo "SUCCESS: Successfully saved ${name}."
}

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
# 1. DATABASE_URL
if [[ -f "/tmp/career_agent_db_url.txt" ]]; then
  DB_URL=$(cat /tmp/career_agent_db_url.txt)
  create_secret "DATABASE_URL" "${DB_URL}"
  # Securely delete the temporary file
  rm -f /tmp/career_agent_db_url.txt
else
  echo "WARNING: /tmp/career_agent_db_url.txt not found. Skipping DATABASE_URL."
fi

# 2. REDIS_URL
if [[ -f "/tmp/career_agent_redis_url.txt" ]]; then
  REDIS_URL=$(cat /tmp/career_agent_redis_url.txt)
  create_secret "REDIS_URL" "${REDIS_URL}"
  # Securely delete the temporary file
  rm -f /tmp/career_agent_redis_url.txt
else
  echo "WARNING: /tmp/career_agent_redis_url.txt not found. Skipping REDIS_URL."
fi

# 3. Third-Party API Secrets (Interactive prompt if empty)
declare -A SECRETS
SECRETS=(
  ["TELEGRAM_API_ID"]="${TELEGRAM_API_ID:-}"
  ["TELEGRAM_API_HASH"]="${TELEGRAM_API_HASH:-}"
  ["TELEGRAM_SESSION_STRING"]="${TELEGRAM_SESSION_STRING:-}"
  ["GMAIL_OAUTH_CLIENT_ID"]="${GMAIL_OAUTH_CLIENT_ID:-}"
  ["GMAIL_OAUTH_CLIENT_SECRET"]="${GMAIL_OAUTH_CLIENT_SECRET:-}"
  ["GMAIL_OAUTH_REFRESH_TOKEN"]="${GMAIL_OAUTH_REFRESH_TOKEN:-}"
)

echo "Checking for third-party API keys..."
for key in "${!SECRETS[@]}"; do
  val="${SECRETS[$key]}"
  
  if [[ -z "${val}" ]]; then
    # If not set in ENV, check if the secret already exists in Secret Manager
    if gcloud secrets describe "${key}" >/dev/null 2>&1; then
      echo "INFO: Secret ${key} already exists in Secret Manager. Skipping prompt."
      continue
    fi
    
    # Prompt user securely (if running interactively)
    echo -n "Enter value for ${key} (or leave blank to skip): "
    read -r -s val < /dev/tty || val=""
    echo "" # Add newline after silent read
  fi
  
  if [[ -n "${val}" ]]; then
    create_secret "${key}" "${val}"
  else
    echo "INFO: Skipping ${key} (no value provided)."
  fi
done

echo "========================================="
echo "SUCCESS: Secrets provisioned successfully!"
echo "========================================="
