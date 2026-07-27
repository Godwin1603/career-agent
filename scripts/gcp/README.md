# GCP Infrastructure Provisioning

This directory contains shell scripts to automatically provision a production-ready Google Cloud architecture for the Career Agent project. 

The infrastructure uses fully managed services exclusively (Cloud SQL, Memorystore, Cloud Tasks, Secret Manager, Cloud Run) and enforces security best practices (Private IP databases, Secret Manager environment mounting, Least-privilege IAM).

## Prerequisites

1.  **Google Cloud CLI (gcloud)** installed and initialized.
2.  **Billing** enabled on your Google Cloud Project.
3.  Authenticate your terminal:
    ```bash
    gcloud auth login
    gcloud auth application-default login
    ```
4. Ensure you have basic tools like `jq` and `curl` installed (standard in Cloud Shell).

## Execution Order

Execute the scripts sequentially from the repository root:

```bash
cd career-agent
bash scripts/gcp/01_enable_apis.sh
bash scripts/gcp/02_service_account.sh
bash scripts/gcp/03_cloud_sql.sh
bash scripts/gcp/04_memorystore.sh
bash scripts/gcp/05_cloud_storage.sh
bash scripts/gcp/06_cloud_tasks.sh
bash scripts/gcp/07_artifact_registry.sh
bash scripts/gcp/08_secret_manager.sh
bash scripts/gcp/09_cloud_run.sh
bash scripts/gcp/10_verify.sh
```

## What Each Script Does

1.  **01_enable_apis**: Activates all required GCP APIs (Compute, SQL, Redis, Secret Manager, Tasks, Vertex, Run, etc.).
2.  **02_service_account**: Creates the `career-agent-worker` service account and binds necessary roles.
3.  **03_cloud_sql**: Sets up VPC peering and provisions a PostgreSQL 15 database instance with no public IP. Generates a random secure password.
4.  **04_memorystore**: Provisions a Redis instance on the default VPC.
5.  **05_cloud_storage**: Creates a regional bucket for object storage.
6.  **06_cloud_tasks**: Provisions the 5 required app queues with production rate limits.
7.  **07_artifact_registry**: Creates a Docker repo.
8.  **08_secret_manager**: Safely loads DB/Redis connection strings and prompts for external API keys (Telegram, Gmail).
9.  **09_cloud_run**: Builds the Docker image and deploys to Cloud Run with Direct VPC Egress for private DB connectivity and native Secret Manager integration.
10. **10_verify**: Hits the deployed `/health/ready` endpoint to ensure the StartupValidator passed.

## Rollback & Cleanup

To destroy the provisioned resources and stop billing, run:

```bash
gcloud run services delete career-agent --region us-central1 --quiet
gcloud sql instances delete career-agent-db-instance --quiet
gcloud redis instances delete career-agent-redis --region us-central1 --quiet
gcloud tasks queues delete portal-application-q --location us-central1 --quiet
# Repeat for other queues...
gcloud storage rm --recursive gs://career-agent-data-${PROJECT_ID}
gcloud iam service-accounts delete career-agent-worker@${PROJECT_ID}.iam.gserviceaccount.com --quiet
```
*(Note: Be careful deleting instances if you need to retain application data).*

## Expected Costs
- **Cloud SQL**: db-custom-1-3840 (approx $30-40/mo depending on usage)
- **Memorystore**: 1GB basic tier (approx $35/mo)
- **Cloud Run / Tasks**: Billed on invocation (highly scalable scale-to-zero, usually free tier for small scale)
- **VPC Egress / Networking**: Negligible for MVP scale.
