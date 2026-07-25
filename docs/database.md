# Database

## Database Selection

**PostgreSQL** was selected as the primary persistent store.

**Reasoning:**

- The data model is inherently relational. Jobs, applications, strategies, outcomes, and resumes have clear foreign-key relationships. A relational model captures these naturally.
- JSONB columns provide flexibility for semi-structured data (raw AI outputs, portal-specific fields) without sacrificing the relational guarantees needed for the rest of the schema.
- Alembic provides mature, reliable schema migration support with SQLAlchemy 2.
- Neon (serverless PostgreSQL) is ideal for the development phase: it offers a free tier, connection pooling via PgBouncer, and instant branching for schema experiments.
- For production on Cloud Run, Neon's serverless connection pooling eliminates the challenge of managing PostgreSQL connections from a stateless, auto-scaling service.

**Alternatives rejected:**

- **MongoDB**: The data model is not document-oriented. Relational integrity (e.g., ensuring an application always references a valid job) is valuable here. MongoDB would sacrifice that for no gain.
- **SQLite**: Not suitable for Cloud Run (ephemeral filesystem) and lacks concurrent write support.
- **Firestore**: GCP-native but document-oriented and lacking in JOIN capabilities. Would require denormalization that complicates the data model.

---

## Tables

### Core Tables

**`jobs`**
Stores every job posting detected from the Telegram channel. This is the central entity of the system.

Fields include: unique identifier, source message ID, company name, role title, location, remote flag, detected application URL, detected email address, detected Google Form URL, salary range, relevance score, detected portal name, application strategy list, processing status, timestamps (created, updated, expires at).

---

**`job_raw_messages`**
Stores the raw, unprocessed text of each Telegram message before AI parsing. Retained temporarily for debugging and re-processing.

Fields include: unique identifier, Telegram message ID, channel ID, raw text content, processing status, timestamps.

This table is temporary by design. Records are deleted after 30 days regardless of processing status.

---

**`applications`**
Records each application attempt. One job can have multiple application records (one per strategy: portal, form, email).

Fields include: unique identifier, foreign key to jobs, strategy type (portal / form / email), status (pending / in-progress / success / failed / skipped), attempt count, last error message, applied at timestamp, timestamps.

---

**`application_events`**
An append-only event log for every state transition of an application. Supports auditing and debugging without mutating the `applications` record history.

Fields include: unique identifier, foreign key to applications, event type, event payload (JSONB), timestamp.

---

**`resumes`**
Tracks every resume version generated or used by the system.

Fields include: unique identifier, label (base / tailored), foreign key to job (nullable for base resume), Cloud Storage path, content hash (for deduplication), timestamps.

---

**`application_resumes`**
Join table linking a specific application to the resume version used for it.

Fields include: foreign key to applications, foreign key to resumes, timestamp.

---

**`notifications`**
Records every notification dispatched to the user, including delivery status.

Fields include: unique identifier, foreign key to `jobs` (nullable), foreign key to `applications` (nullable), notification type, message content, delivery status, timestamps.

Exactly one FK is always populated, and sometimes both. Notifications triggered by job-level events (new job detected, job skipped) reference only `jobs`. Notifications triggered by application outcomes reference both `jobs` and `applications`. Both FKs are nullable at the schema level to accommodate system-level alerts (e.g., dead-letter exhaustion) where an application record may not yet exist.

---

**`portal_configs`**
Stores configuration metadata for each supported career portal (field selectors, submission flow hints, known limitations). Updated manually as portals change.

Fields include: unique identifier, portal name, portal base URL, configuration payload (JSONB), enabled flag, timestamps.

---

**`task_log`**
Tracks every Cloud Task dispatched by the system. Used for idempotency checks and debugging task delivery.

Fields include: unique identifier, Cloud Task name, task type, entity ID, status, created at, completed at, error (if any).

---

## Table Relationships

```
job_raw_messages ──(1:many)──▶ jobs
                                  │
                            (1:many)
                                  │
                            applications
                             │        │
                          (1:many)  (many:1)
                             │        │
                    application_events  application_resumes
                                                │
                                             (many:1)
                                                │
                                             resumes

jobs ──────────────────────────────────────── resumes
(1 job can have 1 tailored resume per strategy)

jobs ──────────────────────────────────────── notifications
(job-level notifications reference the job directly)

applications ─────────────────────────────── notifications
(application-level notifications reference both job and application)

applications ─────────────────────────────── task_log
(1 application has many task attempts)
```

---

## Temporary vs Permanent Tables

| Table | Type | Reason |
|---|---|---|
| `job_raw_messages` | Temporary | Debug/reprocessing only. Deleted after 30 days. |
| `application_events` | Permanent (append-only) | Audit trail for application lifecycle. Retained indefinitely to match `applications` retention and avoid orphaned records. |
| `task_log` | Semi-temporary | Operational. Entries older than 60 days are purged. |
| All other tables | Permanent | Core business data with long-term value. |

---

## Data Retention Strategy

| Table | Retention Period | Cleanup Method |
|---|---|---|
| `job_raw_messages` | 30 days | Scheduled task deletes by `created_at` |
| `task_log` | 60 days | Scheduled task deletes by `created_at` |
| `application_events` | Indefinite | Retained to match `applications` table. Low volume; negligible storage impact. |
| `notifications` | 90 days | Scheduled task deletes by `created_at` |
| `jobs` | Indefinite | Never deleted (small volume, high value) |
| `applications` | Indefinite | Never deleted (audit record) |
| `resumes` (DB record) | Indefinite | Record retained even if GCS file expires |

Cleanup tasks are idempotent and run in batches to avoid long-running transactions.

---

## Redis Usage

Redis is used exclusively for short-lived, operational data. It is not a source of truth.

| Purpose | Key Pattern | TTL | Notes |
|---|---|---|---|
| Idempotency lock | `lock:application:{application_id}` | 10 minutes | Prevents duplicate task execution |
| Deduplication | `dedup:job:{message_id}` | 7 days | Prevents re-processing the same Telegram message |
| Rate limiting | `ratelimit:{portal}:{date}` | 24 hours | Per-portal daily submission cap |
| Session cache | `session:{portal}:{session_id}` | 30 minutes | Playwright browser session tokens if reusable |
| Config cache | `config:portal:{portal_name}` | 1 hour | Avoids repeated DB reads for portal configs |

All Redis keys use short TTLs. If Redis is unavailable, the system falls back to PostgreSQL checks (slower but correct).

---

## Cloud Storage Usage

Google Cloud Storage is used for binary and large text artifacts that are not appropriate for PostgreSQL storage.

| Bucket Path | Content | Retention | Notes |
|---|---|---|---|
| `resumes/base/` | Master resume files (PDF, DOCX) | Indefinite | Manually uploaded by user |
| `resumes/{job_id}/tailored.pdf` | AI-tailored resume per job | 180 days | GCS lifecycle policy auto-deletes |
| `screenshots/{application_id}/` | Browser screenshots for debugging | 30 days | GCS lifecycle policy auto-deletes |
| `attachments/{application_id}/` | Email attachments (resume PDFs sent) | 90 days | GCS lifecycle policy auto-deletes |
| `exports/` | Manual data exports | User-controlled | Never auto-deleted |

GCS lifecycle policies handle automatic deletion based on object age, removing the need for application-level cleanup logic for storage assets.
