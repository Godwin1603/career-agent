#!/usr/bin/env bash
#
# 11_observability.sh
# Provisions foundational monitoring and alerting policies for Career Agent.
#

set -euo pipefail

# -----------------------------------------------------------------------------
# Validation & Configuration
# -----------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-career-agent-503617}"
REGION="${REGION:-us-central1}"
SERVICE_NAME="career-agent"

echo "========================================="
echo "Provisioning Observability & Alerts"
echo "========================================="

gcloud config set project "${PROJECT_ID}"

# -----------------------------------------------------------------------------
# Execution
# -----------------------------------------------------------------------------
# 1. Ensure Monitoring API is enabled
gcloud services enable monitoring.googleapis.com

# 2. Create Notification Channel (Email)
# NOTE: In a real environment, you'd script grabbing the channel ID. 
# Here we'll create the channel and capture its name.
echo "Creating Email Notification Channel..."
CHANNEL_NAME=$(gcloud alpha monitoring channels create \
  --display-name="DevOps Team Email" \
  --type="email" \
  --channel-labels="email_address=devops@example.com" \
  --format="value(name)" || true)

# 3. Create Alert Policy for Cloud Run 5xx Errors
if [[ -n "${CHANNEL_NAME}" ]]; then
  echo "Creating Alert Policy: Cloud Run High 5xx Error Rate"
  cat <<EOF > /tmp/alert-policy.json
{
  "displayName": "Cloud Run High 5xx Error Rate (${SERVICE_NAME})",
  "combiner": "OR",
  "conditions": [
    {
      "displayName": "Cloud Run Revision - Server Error (5xx)",
      "conditionThreshold": {
        "filter": "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"${SERVICE_NAME}\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\"",
        "aggregations": [
          {
            "alignmentPeriod": "300s",
            "crossSeriesReducer": "REDUCE_SUM",
            "perSeriesAligner": "ALIGN_RATE"
          }
        ],
        "comparison": "COMPARISON_GT",
        "duration": "0s",
        "trigger": {
          "count": 1
        },
        "thresholdValue": 0.1
      }
    }
  ],
  "notificationChannels": [
    "${CHANNEL_NAME}"
  ]
}
EOF

  gcloud alpha monitoring policies create --policy-from-file="/tmp/alert-policy.json" || echo "INFO: Policy may already exist."
  rm -f /tmp/alert-policy.json
else
  echo "WARNING: Failed to create notification channel, skipping alert policy creation."
fi

echo "========================================="
echo "SUCCESS: Observability provisioned successfully!"
echo "========================================="
