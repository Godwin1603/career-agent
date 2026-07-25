# Configuration Reference

All runtime configuration is loaded by `src/config.py` using Pydantic `BaseSettings`. Values are sourced from environment variables. No configuration is hard-coded in application logic.

**Secret vs. non-secret variables:**
- **Sensitive variables** (credentials, tokens, connection strings) are stored in Google Secret Manager and injected as environment variables at Cloud Run deploy time.
- **Non-sensitive tuning parameters** (thresholds, limits, intervals) are set as plain environment variables in the Cloud Run service configuration.

No default values are listed here. Every variable must be explicitly set in the deployment environment. A `.env.example` file in the repository root lists all variable names without values and serves as the authoritative checklist for environment setup.

---

## Database

| Variable | Purpose | Module | Secret Manager |
|---|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string. Use the Neon PgBouncer pooling endpoint for Cloud Run compatibility. | `src/core/database.py` | Yes |

---

## Redis

| Variable | Purpose | Module | Secret Manager |
|---|---|---|---|
| `REDIS_URL` | Redis connection URL including host, port, and authentication token if required. | `src/core/redis.py` | Yes |

---

## Google Cloud Platform

| Variable | Purpose | Module | Secret Manager |
|---|---|---|---|
| `GCP_PROJECT_ID` | Google Cloud project ID. Used by all GCP service clients for project scoping. | `src/core/tasks.py`, `src/core/storage.py`, `src/core/secrets.py` | No |
| `GCS_BUCKET_NAME` | Name of the Cloud Storage bucket used for resumes, screenshots, and attachments. | `src/core/storage.py` | No |
| `CLOUD_TASKS_LOCATION` | GCP region where Cloud Tasks queues are provisioned (e.g., `us-central1`). | `src/core/tasks.py` | No |
| `CLOUD_RUN_SERVICE_URL` | The public HTTPS URL of this Cloud Run service. Used to construct Cloud Tasks target URLs. | `src/core/tasks.py` | No |

---

## Cloud Tasks Queue Names

Each queue is referenced by name in the task dispatcher. Queue names must match the actual queues provisioned in GCP.

| Variable | Purpose | Module | Secret Manager |
|---|---|---|---|
| `CLOUD_TASKS_QUEUE_JOB_ENRICHMENT` | Queue for job enrichment tasks (Gemini parsing and scoring). | `src/core/tasks.py` | No |
| `CLOUD_TASKS_QUEUE_PORTAL_APPLICATION` | Queue for portal application tasks (Playwright). | `src/core/tasks.py` | No |
| `CLOUD_TASKS_QUEUE_FORM_APPLICATION` | Queue for Google Form submission tasks. | `src/core/tasks.py` | No |
| `CLOUD_TASKS_QUEUE_EMAIL_APPLICATION` | Queue for cold email dispatch tasks. | `src/core/tasks.py` | No |
| `CLOUD_TASKS_QUEUE_NOTIFICATION` | Queue for user notification tasks. | `src/core/tasks.py` | No |

---

## AI — Gemini

| Variable | Purpose | Module | Secret Manager |
|---|---|---|---|
| `VERTEX_AI_LOCATION` | GCP region for Vertex AI API calls (e.g., `us-central1`). | `src/ai/client.py` | No |
| `GEMINI_MODEL` | Gemini model identifier (e.g., `gemini-2.5-flash`). Controls which model version is used for all AI tasks. | `src/ai/client.py` | No |

---

## Telegram

| Variable | Purpose | Module | Secret Manager |
|---|---|---|---|
| `TELEGRAM_API_ID` | Telegram application API ID. Obtained from [my.telegram.org](https://my.telegram.org). Required for Telethon MTProto authentication. | `src/telegram/listener.py` | Yes |
| `TELEGRAM_API_HASH` | Telegram application API hash. Obtained from [my.telegram.org](https://my.telegram.org). | `src/telegram/listener.py` | Yes |
| `TELEGRAM_SESSION_STRING` | Telethon session string for persistent, stateless authentication. Generated once via an offline script and stored in Secret Manager. Avoids repeated interactive logins. | `src/telegram/listener.py` | Yes |
| `TELEGRAM_CHANNEL_ID` | Numeric ID of the private channel to monitor for job postings. | `src/telegram/listener.py` | No |
| `TELEGRAM_NOTIFY_CHAT_ID` | Numeric ID of the personal chat where user notifications are sent. | `src/telegram/notifier.py` | No |

---

## Gmail

| Variable | Purpose | Module | Secret Manager |
|---|---|---|---|
| `GMAIL_OAUTH_CLIENT_ID` | OAuth 2.0 client ID for Gmail API access. Created in the GCP project's OAuth consent screen. | `src/workers/email_worker.py` | Yes |
| `GMAIL_OAUTH_CLIENT_SECRET` | OAuth 2.0 client secret for Gmail API access. | `src/workers/email_worker.py` | Yes |
| `GMAIL_OAUTH_REFRESH_TOKEN` | Long-lived OAuth refresh token. Generated once via the OAuth authorization flow and stored permanently in Secret Manager. | `src/workers/email_worker.py` | Yes |
| `GMAIL_SENDER_ADDRESS` | The Gmail address from which cold emails are sent. Must match the authenticated account. | `src/workers/email_worker.py` | No |

---

## Application Behavior Tuning

These variables control system behavior and are not sensitive. They are set as plain environment variables and can be adjusted without a code deployment.

| Variable | Purpose | Module | Default Guidance |
|---|---|---|---|
| `RELEVANCE_THRESHOLD` | Minimum AI relevance score (0–100) for a job to be actioned. Jobs scoring below this value are marked `skipped` and no application is attempted. | `src/applications/dispatcher.py` | Start at 60–70 and adjust based on observed job quality. |
| `MAX_PORTAL_APPS_PER_DAY` | Maximum portal applications submitted per portal per calendar day. Enforced via Redis rate limiting. Prevents over-application to a single portal. | `src/workers/portal_worker.py` | 5–10 per portal. |
| `JOB_EXPIRY_DAYS` | Number of days after a job's detected posting date before it is considered too old to apply to. Jobs past this window are marked `skipped` by the dispatcher. | `src/applications/dispatcher.py` | 14 days. |
| `STALE_APPLICATION_WINDOW_MINUTES` | Minutes after the last update before an `in-progress` application is considered stale (Cloud Tasks has stopped retrying). The cleanup scheduler uses this to trigger the dead-letter flow. Must be set longer than `max_attempts × max_backoff_interval` for all queues. | `src/scheduler/cleanup.py` | 90 minutes. |
| `CLEANUP_RUN_INTERVAL_MINUTES` | How frequently the cleanup and stale detection scheduler runs. Set via the Cloud Scheduler trigger interval. | `src/scheduler/cleanup.py` | 30 minutes. |

---

## Cloud Run Service Configuration

These are deployment-level settings, not application-level environment variables. They are set in the Cloud Run service definition.

| Setting | Required Value | Reason |
|---|---|---|
| `min-instances` | `1` | Keeps the Telethon listener always connected. Scale-to-zero would drop the persistent MTProto connection and silently miss job postings. |
| `max-instances` | 2–3 | Sufficient for personal use. Limits concurrent Playwright sessions. |
| Request timeout | 60 minutes | Playwright portal automation sessions may run for several minutes. The default timeout is insufficient. |
| CPU allocation | Always-on (not request-only) | Required for the background asyncio Telethon listener task to remain active between requests. |

---

## Adding a New Configuration Variable

1. Add the field to `src/config.py` as a typed `BaseSettings` attribute.
2. Add the variable to the appropriate section in this document with its purpose, owning module, and whether it should go in Secret Manager.
3. Add the variable name (with no value) to `.env.example`.
4. In production: add the value to Secret Manager (for sensitive variables) or the Cloud Run environment configuration (for non-sensitive variables).
