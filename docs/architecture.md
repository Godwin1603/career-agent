# Architecture

## Overview

career-agent is an event-driven, pipeline-oriented personal automation platform. It monitors a private Telegram channel for job postings, evaluates relevance using AI, attempts automated applications across multiple channels (career portals, Google Forms, email), and notifies the user about outcomes.

The system is designed to run unattended. It is stateful — all decisions, attempts, and outcomes are persisted so the pipeline can resume after failures without duplicate applications.

---

## High-Level Architecture

```
Telegram Channel
      │
      ▼
┌─────────────────┐
│  Telegram Poller│  (Telethon — reads new messages)
└────────┬────────┘
         │ raw job message
         ▼
┌─────────────────┐
│  Job Processor  │  (Gemini Flash — parse, deduplicate, relevance score)
└────────┬────────┘
         │ structured job record
         ▼
┌─────────────────────────────────────────┐
│              PostgreSQL                  │
│  jobs · applications · resumes · logs   │
└────────────────────┬────────────────────┘
                     │
         ┌───────────▼───────────┐
         │   Application Router  │  (decides which strategy to use)
         └───────────┬───────────┘
                     │
      ┌──────────────┼──────────────┐
      │              │              │
      ▼              ▼              ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│  Portal  │  │  Google  │  │   Cold   │
│  Worker  │  │  Form    │  │  Email   │
│(Playwright│  │  Worker  │  │  Worker  │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    │ outcome
                    ▼
           ┌─────────────────┐
           │  Notifier       │  (Telegram message to user)
           └─────────────────┘
```

---

## Telegram Listener Deployment Model

The Telethon listener maintains a persistent MTProto connection to Telegram. This is a long-running socket connection — not an HTTP request handler. It conflicts with Cloud Run's default scale-to-zero behavior, which terminates instances during idle periods. A terminated listener would silently miss job postings with no error surfaced.

**Deployment Decision: `min-instances = 1`**

The Cloud Run service is configured with a minimum of one instance always running. This prevents scale-to-zero and ensures the Telethon connection is never dropped.

| Property | Value |
|---|---|
| Cloud Run `min-instances` | `1` |
| Cloud Run `max-instances` | 2–3 (sufficient for personal use) |
| Cost impact | Negligible at personal scale (one minimal instance ≈ $3–5/month) |
| Reconnection on failure | Handled automatically by Telethon's built-in reconnection logic |

**Startup behavior:**
When the Cloud Run instance starts, the Telethon listener is initialized as part of the FastAPI startup lifecycle. It runs as a background asyncio task for the lifetime of the process. Incoming messages are immediately enqueued to Cloud Tasks for durable handling — the listener performs no AI or database work itself.

**Why not polling:**
A Cloud Scheduler-driven polling approach would introduce latency between job posting and detection equal to the poll interval. It also requires storing a "last seen message ID" checkpoint and careful handling of missed messages during downtime. The persistent connection approach is simpler and more reliable at this scale.

---

## Event-Driven Workflow

The system is driven by a sequence of discrete, asynchronous events. Each step produces an output that triggers the next step. No step blocks another.

| Step | Trigger | Action | Output |
|---|---|---|---|
| 1. Ingest | New Telegram message | Parse raw text | Raw job record |
| 2. Enrich | Job record created | Gemini evaluates relevance, extracts metadata | Structured job with score |
| 3. Route | Job scored above threshold | Application Router selects strategy | Task enqueued |
| 4. Apply | Task dequeued by worker | Execute application strategy | Outcome record |
| 5. Notify | Outcome recorded | Send Telegram notification to user | User informed |
| 6. Retry | Failed task | Re-enqueue with backoff | Retry attempt |
| 7. Expire | Job too old | Mark as expired, skip | No action |

---

## Module Interaction

```
┌──────────────────────────────────────────────────────────────┐
│                        FastAPI Service                        │
│                                                              │
│  ┌────────────┐   ┌─────────────┐   ┌────────────────────┐  │
│  │  Telegram  │   │  AI Engine  │   │  Application       │  │
│  │  Listener  │──▶│  (Gemini)   │──▶│  Router            │  │
│  └────────────┘   └─────────────┘   └────────┬───────────┘  │
│                                               │              │
│  ┌────────────────────────────────────────────▼───────────┐  │
│  │                   Task Dispatcher                       │  │
│  │              (Google Cloud Tasks)                       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌────────────┐   ┌────────────┐   ┌────────────────────┐   │
│  │  Portal    │   │  Form      │   │  Email             │   │
│  │  Worker    │   │  Worker    │   │  Worker            │   │
│  └────────────┘   └────────────┘   └────────────────────┘   │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │                    Shared Services                      │  │
│  │   Resume Manager · Notifier · Storage · Secret Manager  │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

All modules share the same FastAPI process on Cloud Run. Workers are triggered via HTTP callbacks from Cloud Tasks, not separate processes.

---

## Queue Architecture

Google Cloud Tasks is used as the task queue.

**Queues defined:**

| Queue Name | Purpose | Max Attempts | Backoff |
|---|---|---|---|
| `job-enrichment` | Gemini scoring and metadata extraction | 3 | Exponential |
| `portal-application` | Playwright-based portal submissions | 5 | Exponential |
| `form-application` | Google Form submissions | 3 | Exponential |
| `email-application` | Cold email dispatch via Gmail API | 3 | Fixed |
| `notification` | Telegram user notifications | 5 | Fixed |

Each task payload contains:
- Task type identifier
- Entity ID (job ID, application ID)
- Retry count
- Scheduled time

Tasks are delivered as HTTP POST requests to dedicated FastAPI endpoints within the same Cloud Run service.

---

## Worker Lifecycle

```
Cloud Tasks
    │
    │  HTTP POST /tasks/{task-type}
    ▼
FastAPI endpoint (task handler)
    │
    ├── Load entity from PostgreSQL
    ├── Validate preconditions (not already completed, not expired)
    ├── Acquire Redis lock (prevent duplicate execution)
    ├── Execute strategy
    │     ├── Success → update DB to success, release lock, enqueue notification, return HTTP 200
    │     ├── Retryable failure → log error, release lock, return HTTP 500 (Cloud Tasks retries)
    │     └── Terminal failure → update DB to failed, release lock, enqueue notification, return HTTP 200
    └── HTTP response signals retry intent to Cloud Tasks (see Failure Classification)
```

**Failure Classification:**

The HTTP response code returned by the task handler signals retry intent to Cloud Tasks. Not all failures are equal — the system distinguishes retryable infrastructure failures from terminal business-logic outcomes.

| Failure Type | Examples | HTTP Response | Cloud Tasks Behavior |
|---|---|---|---|
| Retryable — infrastructure | Database unavailable, Redis unreachable, GCS timeout, Gemini API 5xx | HTTP 500 | Cloud Tasks retries with exponential backoff |
| Terminal — business logic | Portal rejected application, job already closed, application already succeeded | HTTP 200 | No retry. Outcome recorded internally. |
| Terminal — permanently failed | Max retry attempts reached, dead-letter flow triggered | HTTP 200 | Stale detector transitions record to `permanently_failed` |

**Redis lock behavior:**
Redis locks use the application ID as the key with a TTL slightly longer than the expected task execution window. This prevents duplicate execution when Cloud Tasks delivers the same task more than once (at-least-once delivery guarantee). If Redis is temporarily unavailable, the system falls back to a PostgreSQL-based idempotency check before executing.

---

## Dead-Letter Strategy

When a task exhausts all retry attempts, Cloud Tasks stops delivering it. Without explicit handling, the application record remains in `in-progress` state indefinitely — a silent failure the user is never informed about.

**Dead-letter flow:**

```
Max retries exhausted (Cloud Tasks stops delivery)
    │
    ▼
Application record remains in `in-progress` state in PostgreSQL
    │
    ▼
Stale application detector (part of cleanup scheduler, runs every N minutes)
    │
    ├── Detects: status = in-progress AND last_updated older than stale window
    ├── Transitions: status → permanently_failed
    ├── Appends: terminal ApplicationEvent (reason: max retries exhausted)
    └── Enqueues: high-priority notification task
            │
            ▼
    User receives Telegram notification:
    "⚠️ Application to {company} for {role} could not be submitted.
     Strategy: {strategy}. Manual review required."
```

**Per-queue retry and stale detection configuration:**

| Queue | Max Attempts | Stale Detection Window | User Notified on Exhaustion |
|---|---|---|---|
| `job-enrichment` | 3 | 30 minutes | No — job is marked skipped |
| `portal-application` | 5 | 90 minutes | Yes — manual review required |
| `form-application` | 3 | 60 minutes | Yes — manual review required |
| `email-application` | 3 | 45 minutes | Yes — manual review required |
| `notification` | 5 | 20 minutes | No — silent drop is acceptable |

The stale detection window is always set longer than `max_attempts × max_backoff_interval` to avoid false positives from tasks still within their retry cycle.

---

## Data Flow

```
Telegram message text
    │
    ▼ (Telethon)
Raw text stored → job_raw_messages table
    │
    ▼ (Gemini Flash)
Structured fields extracted:
  - company name
  - role title
  - location / remote flag
  - application URL
  - email address
  - Google Form URL
  - salary (if present)
  - relevance score (0–100)
  - detected portal
    │
    ▼
jobs table populated
    │
    ▼ (Application Router)
Threshold check (score ≥ configured minimum)
    │
    ├── Below threshold → mark as skipped
    └── Above threshold
            │
            ├── Portal URL detected → enqueue portal-application
            ├── Form URL detected  → enqueue form-application
            ├── Email detected     → enqueue email-application
            └── Multiple detected  → enqueue all strategies in parallel
```

---

## Resume Manager Architecture

The Resume Manager is responsible for selecting and serving the correct resume for each application.

**Design principles:**
- A base resume is stored in Cloud Storage.
- Gemini Flash generates a tailored version for each application based on the job description.
- All generated resumes are cached in Cloud Storage to avoid regeneration.
- PostgreSQL tracks which resume version was used per application.

```
Application triggered
    │
    ▼
Resume Manager
    │
    ├── Check if tailored resume exists in Cloud Storage for this job
    │       └── Yes → serve cached version
    │
    └── No → generate tailored resume
                │
                ├── Fetch base resume from Cloud Storage
                ├── Send to Gemini Flash with job description
                ├── Receive tailored resume text
                ├── Convert to PDF (via reportlab or equivalent)
                ├── Upload to Cloud Storage
                └── Record version in PostgreSQL
```

**Cache key:** `resumes/{job_id}/{strategy}/tailored.pdf`

The cache key includes both `job_id` and `strategy` (portal / form / email). This prevents collisions when multiple strategies are applied to the same job — a portal application and an email application for the same job may require differently formatted resume variants (e.g., single-page format vs. one with an introductory paragraph).

**Cache invalidation:** Each tailored resume record in PostgreSQL stores the content hash of the base resume used to generate it. Before serving a cached resume, the system checks whether the current base resume's hash matches the hash stored on the cached record. If the hashes differ (the user has updated their base resume), the cache is considered stale and a new tailored version is generated and uploaded.

---

## Browser Session Management

Playwright runs in headless Chromium mode inside the Cloud Run container. The browser binary is installed as part of the container image at build time. Each Cloud Tasks invocation launches a fresh, isolated browser context — no session state is shared between invocations.

**Session lifecycle per invocation:**

```
Portal worker triggered (Cloud Tasks HTTP delivery)
    │
    ▼
Launch fresh headless Chromium context
    │
    ▼
Load portal credentials from Google Secret Manager
    │
    ▼
Navigate to portal login page and authenticate
    │
    ├── Authentication succeeds → session cookies established in browser context
    │
    ▼
Execute application form submission with tailored resume attached
    │
    ▼
Capture confirmation screenshot → upload to GCS
    │
    ▼
Browser context closed and discarded (cookies not persisted)
```

**Persistence decisions:**

| Concern | Decision | Reasoning |
|---|---|---|
| Browser cookies | Not persisted across invocations | Stateless invocations simplify debugging and avoid stale session bugs |
| Portal credentials | Stored in Secret Manager per portal | Credentials are sensitive and long-lived |
| Short-lived session tokens | Stored in Redis with 30-minute TTL if reusable within a Cloud Tasks batch window | Redis TTL aligns with typical portal session duration |
| Browser binary | Installed in container image | Must be present at runtime; cannot be installed on-demand on Cloud Run |

**Authentication failure handling:**
If portal login fails (wrong credentials, CAPTCHA prompt, MFA challenge), the worker captures a screenshot, records the error on the application record, and returns HTTP 500 to trigger a Cloud Tasks retry. If login consistently fails across all retry attempts, the dead-letter flow is triggered and the user receives a high-priority Telegram notification.

**Portal bot detection:**
Some portals actively detect and block automated browsers via CAPTCHA, IP rate limiting, or behavioral fingerprinting. The `portal_configs` table stores portal-specific interaction hints (timing delays, preferred browser engine, known friction points). Each portal handler is responsible for applying these hints during automation.

---

## Notification Flow

```
Application outcome recorded (or job-level event)
    │
    ▼
Notification task enqueued
    │  Payload: entity_type (job | application), entity_id, notification_type
    ▼
Notifier worker executes
    │
    ├── Load entity (job or application) from PostgreSQL
    ├── Compose message from outcome template
    │       Fields: company, role, strategy (if applicable), status, timestamp, URL
    │
    ▼
Telegram via Telethon (user's personal account)
    │
    ▼
User receives message in personal Telegram chat
    │
    ▼
Notification record updated: delivery_status → sent
```

**Notification entity references:**

Notifications may reference a job, an application, or both, depending on the triggering event. The `notifications` table carries a nullable FK to `jobs` and a nullable FK to `applications`.

| Notification Type | Entity Referenced | FK to `jobs` | FK to `applications` |
|---|---|---|---|
| New relevant job found | Job | ✓ | — |
| Job skipped (below threshold) | Job | ✓ | — |
| Application submitted | Application | ✓ | ✓ |
| Application failed — retry pending | Application | ✓ | ✓ |
| Application permanently failed | Application | ✓ | ✓ |

**Notification triggers and priority:**

| Event | Message Type | Priority |
|---|---|---|
| Job detected (above threshold) | Info: new relevant job found | Normal |
| Application submitted | Success: applied to `{company}` for `{role}` | Normal |
| Application failed — retry pending | Info: retry attempt N of M in progress | Low |
| Application permanently failed | Warning: manual review required | High |
| Job skipped (below threshold) | Optional, configurable | Low |

---

## AI Responsibility Boundaries

Gemini Flash is used only where semantic reasoning over unstructured text is genuinely required. All other decisions are made by deterministic business logic. This boundary is intentional — AI introduces latency, cost, and non-determinism that is only justified where rule-based approaches fail.

**Where AI is used:**

| Task | Justification |
|---|---|
| Job field extraction | Input is unstructured natural language. Field positions vary by post author. Regex is not a viable long-term solution. |
| Relevance scoring | Requires semantic understanding of role fit, seniority, and domain alignment — not mechanical field matching. |
| Resume tailoring | Requires language generation and semantic mapping of candidate skills to a specific job's requirements. |

**Where AI is NOT used:**

| Task | Why deterministic logic is used instead |
|---|---|
| Application strategy routing | Determined by URL patterns and email presence in the job record. Pattern matching is reliable and auditable. |
| Deduplication | Determined by Telegram message ID exact match. No ambiguity. |
| Retry and failure classification | Determined by attempt count and error type. Pure state machine. |
| Relevance threshold check | Comparing a numeric AI score to a configured numeric value. |
| Notification dispatch | Triggered by deterministic state transitions. No interpretation required. |
| Cleanup scheduling | Determined by timestamps vs. configured retention periods. |
| Portal configuration lookup | Determined by exact portal name match to the `portal_configs` table. |

**AI failure handling:**
If a Gemini API call fails (timeout, 5xx response, or malformed JSON that fails Pydantic validation), it is treated as a **retryable infrastructure failure**. The task returns HTTP 500 and Cloud Tasks retries with exponential backoff. The system does not fall back to regex-based extraction — incomplete or incorrect extraction is worse than a clean retry.

---

## Configuration Ownership

All runtime-tunable parameters are owned by `src/config.py` and populated from environment variables. No business logic module hard-codes values that a deployer may need to adjust. See `docs/configuration.md` for the complete environment variable reference.

**Key tunable parameters and their owners:**

| Parameter | Controls | Consuming Module |
|---|---|---|
| `RELEVANCE_THRESHOLD` | Minimum AI score (0–100) for a job to be actioned | Application dispatcher |
| `MAX_PORTAL_APPS_PER_DAY` | Per-portal daily application rate limit | Portal worker |
| `JOB_EXPIRY_DAYS` | Days after posting when a job is no longer eligible for application | Application dispatcher |
| `STALE_APPLICATION_WINDOW_MINUTES` | Minutes before an in-progress application is considered stale | Cleanup scheduler |
| `CLEANUP_RUN_INTERVAL_MINUTES` | Frequency of stale detection and data retention cleanup runs | Cleanup scheduler |
| `TELEGRAM_CHANNEL_ID` | The channel to monitor for job postings | Telegram listener |
| `TELEGRAM_NOTIFY_CHAT_ID` | The chat to send user notifications to | Notifier |
| Cloud Tasks queue names | Target queues for each task type | Task dispatcher |

---

## Cleanup Strategy

| Resource | Retention | Cleanup Trigger |
|---|---|---|
| `job_raw_messages` | 30 days | Scheduled daily task |
| Completed application artifacts | 90 days | Scheduled weekly task |
| Failed task logs | 60 days | Scheduled daily task |
| Cached resumes (Cloud Storage) | 180 days | GCS lifecycle policy |
| Redis locks | TTL auto-expiry | Automatic |
| Redis deduplication keys | 7 days TTL | Automatic |

Cleanup is implemented as periodic Cloud Tasks enqueued by a Cloud Scheduler job. Cleanup tasks run during off-peak hours and are idempotent.
