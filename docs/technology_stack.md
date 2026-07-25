# Technology Stack

## Language: Python 3.12

Python is the natural choice for this project. The entire ecosystem this project depends on — Telethon, Playwright, Gemini SDKs, SQLAlchemy, Alembic, FastAPI — is Python-native. Python 3.12 specifically brings meaningful performance improvements, better error messages, and full support for the `asyncio` patterns this project relies on throughout.

---

## Backend Framework: FastAPI

**Why FastAPI:**

FastAPI is the correct choice for an async-first application that primarily processes task payloads and exposes internal HTTP endpoints.

- **Native async support.** The entire pipeline is I/O-bound: database calls, AI API calls, Playwright browser automation, Gmail API. FastAPI's async request handlers mean the server never blocks waiting for one operation while another is ready.
- **Pydantic v2 integration.** Task payloads and configurations are validated automatically at the boundary with zero boilerplate.
- **Lightweight.** This is a personal automation tool, not a public API. FastAPI's minimal overhead and lack of mandatory ceremony is appropriate.
- **Dependency injection.** Database sessions, Redis clients, and other shared resources are cleanly managed via FastAPI's dependency injection system.

**Why not Django:**
Django's synchronous ORM, batteries-included defaults, and admin interface are all irrelevant to this project. It would add weight without benefit.

**Why not Flask:**
Flask is synchronous by default. Bolting async onto Flask is awkward. FastAPI provides async natively without compromise.

---

## Database: PostgreSQL via Neon

**Why PostgreSQL:**

Covered in detail in `database.md`. In summary: the data model is relational, Alembic/SQLAlchemy 2 integration is mature, and Neon's serverless PostgreSQL is ideal for Cloud Run's stateless, connection-sensitive deployment model.

**Why Neon specifically:**

- Serverless connection pooling (PgBouncer built-in) solves the cold-start connection spike problem inherent in Cloud Run.
- Free tier is sufficient for development and early production.
- Instant database branching allows safe schema experimentation.
- Standard PostgreSQL wire protocol — no vendor lock-in at the application layer.

**Why not MongoDB:**
No benefit for a relational data model. Would sacrifice referential integrity for no gain.

**Why not Firestore:**
Document model is a poor fit. Lacks JOIN semantics. Strong GCP bias without compelling advantage over PostgreSQL.

---

## ORM: SQLAlchemy 2

SQLAlchemy 2 is the standard Python ORM for production applications. The 2.0 release brought a fully async-native API that works naturally with FastAPI and asyncio. Its explicit session management aligns well with the dependency injection pattern used throughout the project.

Alembic, the standard migration tool, is authored by the same team and integrates without friction.

---

## Validation: Pydantic v2

Pydantic v2 is significantly faster than v1 due to its Rust core. It is used for:
- Validating and structuring AI responses from Gemini before they touch the database.
- Defining task payload schemas for Cloud Tasks.
- Validating all configuration loaded from environment variables.

FastAPI's native Pydantic v2 integration means request and response validation is automatic.

---

## Cache: Redis

Redis is used for short-lived operational data: distributed locks, deduplication keys, rate limits, and session caches. It is not a primary store.

The key architectural role Redis plays is **idempotency enforcement**. Cloud Tasks guarantees at-least-once delivery. Redis locks ensure that if the same task is delivered twice (which happens), only one execution succeeds.

A managed Redis instance (e.g., Redis Cloud free tier, or a minimal Memorystore instance) is appropriate. The application is designed to degrade gracefully if Redis is temporarily unavailable by falling back to PostgreSQL-based checks.

---

## Queue: Google Cloud Tasks

**Why Cloud Tasks:**

- **Durable task delivery.** Unlike an in-process queue, Cloud Tasks survives application restarts. If the Cloud Run instance is replaced, enqueued tasks are not lost.
- **Built-in retry with backoff.** Configurable retry counts and exponential backoff per queue are essential for portal automation (which will fail transiently).
- **HTTP-native.** Tasks are delivered as HTTP requests to FastAPI endpoints. No separate worker process or queue consumer is needed — the same Cloud Run service handles both API requests and task execution.
- **Native GCP integration.** No additional infrastructure to manage. IAM-based authentication is already in place.

**Why not Celery:**
Celery requires a broker (typically RabbitMQ or Redis) and separate worker processes. For a personal-scale project on Cloud Run, this adds operational complexity without meaningful benefit. Cloud Tasks removes the need for a broker and a separate worker fleet.

**Why not Pub/Sub:**
Pub/Sub is optimized for high-throughput fan-out messaging. This project has low message volume and needs per-task retry semantics, scheduling, and deduplication — which Cloud Tasks handles directly. Pub/Sub would require building these features on top.

---

## Cloud Platform: Google Cloud Run

**Why Cloud Run:**

- **Serverless, no infrastructure management.** The project runs on Cloud Run without managing VMs, container orchestration, or scaling rules. It scales to zero when idle, which is important for a personal tool that runs periodically.
- **HTTP-native.** Cloud Run instances receive HTTP requests — consistent with how Cloud Tasks delivers task payloads.
- **GCP ecosystem alignment.** Cloud Tasks, Cloud Storage, Secret Manager, and Cloud Scheduler are all first-party integrations that work with Cloud Run's IAM model without additional configuration.
- **Container-based.** The application is packaged as a container, which eliminates environment drift between development and production.

**Why not Cloud Functions:**
Functions impose a 60-minute (or less) execution limit and are not suited for long-running Playwright browser sessions. Cloud Run supports longer request timeouts (up to 60 minutes) and can run stateful browser processes.

**Why not a VM (Compute Engine):**
A permanently-running VM is expensive and requires OS-level maintenance. Cloud Run is cheaper and operationally simpler for this workload.

---

## Telegram Integration: Telethon

**Why Telethon:**

Telethon is the most complete Python client for the Telegram MTProto API (the full Telegram API, not just the Bot API).

- **Channel monitoring.** The job source is a private Telegram channel. Monitoring a channel as a user (not a bot) requires the MTProto API. The Telegram Bot API does not support reading from arbitrary channels.
- **Event-driven listener.** Telethon provides an event system that fires a callback when new messages arrive, making it easy to integrate with the async pipeline.
- **User-mode notifications.** Sending notifications back to the user's personal chat can also be done via Telethon without maintaining a separate bot token (though a bot token can be used for the notification path if preferred).

**Why not the Telegram Bot API directly:**
The Bot API cannot monitor channels the bot is not explicitly added to as an admin. The job source is a private channel the user is a member of as a regular user — which only the MTProto API can access.

---

## Browser Automation: Playwright

**Why Playwright:**

- **Async-native.** Playwright's Python async API integrates without friction into the FastAPI/asyncio stack. No threads required.
- **Chromium, Firefox, WebKit.** Multiple browser engine support is valuable when different portals work better on different engines.
- **Reliable element interaction.** Playwright's auto-waiting mechanism handles dynamically-loaded portal forms without manual sleep calls.
- **Screenshot and trace capture.** Built-in screenshot and tracing support is essential for debugging failed application attempts.

**Why not Selenium:**
Selenium's architecture (separate WebDriver process) is older and more brittle. Playwright's CDP-based approach is more reliable for modern JavaScript-heavy portals. Playwright's async API is also a first-class citizen, not an afterthought.

**Why not Requests/BeautifulSoup:**
Career portals are JavaScript-rendered single-page applications. HTTP-only scraping cannot interact with their forms.

---

## AI: Gemini Flash 3

**Why Gemini Flash 3:**

- **Speed.** Flash models are optimized for low latency. The job enrichment step happens in the critical path between message receipt and task dispatch. Speed matters.
- **Cost.** Flash is significantly cheaper than Pro-tier models. At personal use scale, this matters.
- **Long context.** Gemini's long context window is valuable for resume tailoring — the full job description and the full base resume can be sent in a single prompt.
- **GCP-native.** Gemini is accessed via Vertex AI, which integrates with the same GCP project, IAM, and billing as the rest of the infrastructure.
- **Structured output.** Gemini Flash supports JSON-mode output, enabling reliable field extraction from unstructured job posting text.

**Why not GPT-4o or Claude:**
Both are capable alternatives, but they require separate API accounts and billing outside GCP. Gemini keeps everything within a single cloud vendor, simplifying IAM, billing, and secret management. At the quality level required for text extraction and resume tailoring, Gemini Flash is sufficient.

---

## Storage: Google Cloud Storage

**Why GCS:**

- **Managed, durable object storage.** No servers to manage. Files are replicated automatically.
- **Lifecycle policies.** GCS lifecycle rules handle automatic file deletion by age — removing the need to implement cleanup logic in the application for stored artifacts.
- **GCP-native.** Same project, same IAM, same billing.
- **Large file support.** PDFs and HTML resume templates are not appropriate for PostgreSQL storage. GCS handles binary objects correctly.

**Why not storing files in PostgreSQL:**
PostgreSQL BYTEA columns work but are not designed for large binary storage. They bloat the database and complicate backup strategies. GCS is the correct tool for binary artifacts.

---

## Email: Gmail API

**Why Gmail API:**

The user wants to send cold emails from their personal Gmail account. The Gmail API is the only correct choice for this — it authenticates as the user's Google account and sends mail through their actual mailbox, not a third-party SMTP relay.

- **Deliverability.** Emails sent via Gmail's own API have the best deliverability of any option because they originate from a real, established Gmail account.
- **No SMTP configuration.** No need to manage SMTP credentials, TLS settings, or relay services.
- **GCP OAuth integration.** The same GCP project that runs the application can hold the OAuth credentials.

**Why not SendGrid or Mailgun:**
These are transactional email services designed for applications sending to customers. Using them for personal cold outreach from a personal account is incorrect both technically and from a deliverability perspective.

**Why not SMTP directly to Gmail:**
Google has deprecated basic auth SMTP for non-Google Workspace accounts. OAuth-based SMTP works but is equivalent in complexity to the Gmail API with worse tooling support.

---

## Secrets Management: Google Secret Manager

All sensitive configuration (database URL, API keys, OAuth tokens, Telegram session strings) is stored in Google Secret Manager. Cloud Run services access secrets via environment variables injected at deploy time or via direct API calls at runtime. This eliminates secrets from source code, Docker images, and environment files.

---

## Migrations: Alembic

Alembic is the standard migration tool for SQLAlchemy. It generates versioned migration scripts that can be applied, rolled back, and reviewed as part of the development workflow. Every schema change produces a new migration file committed to the repository.
