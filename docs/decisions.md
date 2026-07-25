# Architecture Decision Records

This document records every significant architectural decision made for career-agent. Each record captures the context, the decision, the alternatives considered, and the reasoning. Records are immutable once written. If a decision is reversed, a new record supersedes it.

---

## ADR-001 — Primary Database

**Status:** Accepted

**Context:**
The system needs to persist jobs, applications, resumes, event logs, and configuration. The data has clear relationships between entities (a job has many applications; an application references a resume).

**Decision:** PostgreSQL (via Neon serverless)

**Alternatives Rejected:**
- **MongoDB** — Document model is a poor fit for relational data. Referential integrity is valuable and MongoDB does not enforce it natively. No advantages for this use case.
- **Firestore** — GCP-native but document-oriented. Lacks JOIN semantics. Would require denormalizing data that is naturally relational.
- **SQLite** — Cannot run on Cloud Run (ephemeral filesystem). No concurrent write support.

**Reasoning:**
Relational data model. Mature tooling (SQLAlchemy 2, Alembic). Neon solves the Cloud Run connection-pooling problem with built-in PgBouncer. Standard PostgreSQL wire protocol prevents vendor lock-in.

---

## ADR-002 — Task Queue

**Status:** Accepted

**Context:**
The system dispatches asynchronous tasks (job enrichment, portal applications, email sending, notifications). Tasks must survive application restarts, support retry with backoff, and not require a separately managed broker or worker fleet.

**Decision:** Google Cloud Tasks

**Alternatives Rejected:**
- **Celery + Redis/RabbitMQ** — Requires a broker process and separate Celery worker processes. Adds operational complexity (two additional managed services) for a personal-scale project. Overkill.
- **Pub/Sub** — Optimized for high-throughput fan-out. Lacks built-in per-task retry semantics, scheduling, and deduplication that Cloud Tasks provides natively.
- **In-process asyncio queue** — Does not survive process restarts. Tasks would be lost on Cloud Run instance replacement or crash.
- **Dramatiq** — Still requires a broker. Same objection as Celery.

**Reasoning:**
Cloud Tasks is HTTP-native (tasks are delivered as HTTP requests to FastAPI endpoints), requires no broker, is fully managed, supports configurable retry with exponential backoff, and is natively integrated with GCP IAM.

---

## ADR-003 — Compute Platform

**Status:** Accepted

**Context:**
The system runs unattended. It needs to handle HTTP requests (from Cloud Tasks), run Playwright browser sessions, and scale to zero when idle.

**Decision:** Google Cloud Run

**Alternatives Rejected:**
- **Cloud Functions** — Imposes strict execution time limits (max 60 minutes, often less). Playwright browser sessions can run longer. Cloud Functions is not suitable for stateful browser automation.
- **Compute Engine VM** — A permanently-running VM is expensive and requires OS-level maintenance. Unnecessary for a personal tool with low and bursty traffic.
- **GKE** — Kubernetes cluster management is extreme overengineering for a single-service personal application.
- **App Engine** — Less flexible than Cloud Run for container-based deployments. Fewer controls over runtime environment.

**Reasoning:**
Cloud Run is serverless, container-based, integrates natively with all other GCP services in use, and supports the longer request timeouts needed for Playwright automation.

**Known constraint — Telethon listener:**
The Telethon MTProto listener requires a persistent connection that conflicts with Cloud Run's default scale-to-zero behavior. To resolve this, the Cloud Run service is configured with `min-instances = 1`, keeping one instance always running. Scale-to-zero is therefore not achieved for this service. At personal-use scale the cost of one always-on minimal Cloud Run instance is negligible (approximately $3–5/month) and is an accepted trade-off. The full rationale is documented in the "Telegram Listener Deployment Model" section of architecture.md.

---

## ADR-004 — AI Model

**Status:** Accepted

**Context:**
The system uses AI for: structured field extraction from raw job text, relevance scoring, and resume tailoring. The AI calls are in the critical path of job processing (latency matters) and will be called frequently (cost matters).

**Decision:** Gemini Flash 3

**Alternatives Rejected:**
- **GPT-4o (OpenAI)** — Capable but requires a separate API account and billing outside GCP. Adds cross-vendor complexity. Gemini is sufficient for the required tasks and stays within the GCP ecosystem.
- **Claude (Anthropic)** — Same objection as GPT-4o. Quality advantage does not justify the operational complexity of a second AI vendor.
- **Gemini Pro** — Slower and more expensive than Flash. For text extraction and resume tailoring, Flash quality is sufficient. Pro is reserved for tasks where Flash is demonstrably inadequate.
- **Open-source self-hosted (Llama, Mistral)** — Self-hosting an LLM adds infrastructure complexity that is inappropriate for a personal automation tool.

**Reasoning:**
Gemini Flash is fast, cost-effective, supports structured JSON output, and is natively accessible via Vertex AI within the same GCP project. Long context window supports full resume + job description in a single prompt.

---

## ADR-005 — Telegram Integration Library

**Status:** Accepted

**Context:**
The job source is a private Telegram channel. The system needs to monitor it for new messages as a regular user (not as a bot admin).

**Decision:** Telethon (MTProto client)

**Alternatives Rejected:**
- **Telegram Bot API (python-telegram-bot, aiogram)** — The Bot API only allows bots to receive messages from chats/channels where the bot is an admin. The job source channel is a private channel the user is a member of as a regular user. The Bot API cannot access it.
- **Official Telegram client libraries** — No official Python client library exists for the MTProto API beyond the apps themselves.

**Reasoning:**
Telethon implements the full Telegram MTProto protocol, enabling the application to act as a user client and receive messages from any channel the user is a member of. It is the only viable library for this requirement.

**Known risk — Telegram Terms of Service:**
Using a user account (not a bot) for automated behavior is subject to Telegram's Terms of Service restrictions on automation. If Telegram detects bot-like behavior on a user account, the account may be rate-limited or suspended. This risk is significant because the Telegram account is likely the user's primary personal account.

Mitigations:
- The tool is a passive reader only. It does not send messages to the channel, add users, or interact with the channel in any active way.
- Message processing rate is very low (a few messages per day from one channel).
- The session string is stored in Secret Manager and survives restarts without requiring repeated logins, which are more detectable patterns than a persistent session.
- Telethon is widely used for legitimate read-only channel monitoring without reported enforcement by Telegram.

This risk is documented as a conscious, accepted decision. If the primary account is ever at risk, an alternative approach exists: add a dedicated Telegram bot as an admin to the channel and forward matching messages to a bot-accessible chat, allowing the Bot API to be used for reading instead.

---

## ADR-006 — Browser Automation Library

**Status:** Accepted

**Context:**
Career portals are JavaScript-rendered SPAs. Automating form submission requires a real browser. The application is async-first.

**Decision:** Playwright

**Alternatives Rejected:**
- **Selenium** — Older architecture (WebDriver process-per-browser). More brittle. Async support is not first-class. Playwright's CDP-based approach is more reliable for modern SPAs.
- **Puppeteer** — Node.js only. The project is Python.
- **Requests + BeautifulSoup** — Cannot interact with JavaScript-rendered pages or dynamic forms.
- **Scrapy** — Same limitation as Requests. Not suitable for form submission.

**Reasoning:**
Playwright has a first-class Python async API, supports multiple browser engines (important for portal compatibility), has reliable auto-waiting for dynamic elements, and includes screenshot and tracing capabilities essential for debugging failed automation.

---

## ADR-007 — Email Sending Method

**Status:** Accepted

**Context:**
The system sends cold application emails from the user's personal Gmail account. Deliverability and authenticity are critical.

**Decision:** Gmail API (OAuth2)

**Alternatives Rejected:**
- **SendGrid / Mailgun / Postmark** — Third-party transactional email services designed for application-to-customer communication. Using them for personal outreach from a personal Gmail account is incorrect. They would send from a different domain, reducing authenticity and deliverability.
- **SMTP directly to Gmail** — Google has deprecated basic authentication SMTP. OAuth-based SMTP works but is equivalent in complexity to the Gmail API with worse library support and less visibility into delivery status.
- **Self-hosted SMTP (Postfix)** — Significant deliverability challenges. Requires SPF/DKIM/DMARC configuration. Overkill and unnecessary for a personal tool.

**Reasoning:**
Sending through Gmail's own API ensures emails originate from the user's established Gmail account with maximum deliverability. OAuth credentials are stored in Secret Manager. The Gmail API provides delivery confirmation and supports attachments.

---

## ADR-008 — Cache Layer

**Status:** Accepted

**Context:**
The system needs distributed locks (to prevent duplicate task execution under Cloud Tasks at-least-once delivery), deduplication keys, and ephemeral rate limiting data.

**Decision:** Redis

**Alternatives Rejected:**
- **PostgreSQL advisory locks** — Viable for locking but not for TTL-based deduplication or rate limiting. Would add load to the primary database for operational concerns.
- **Memcached** — No native TTL-on-set semantics as clean as Redis. No persistence option if needed in future. Redis is the industry standard for this use case.
- **In-memory (process-local)** — Does not work across multiple Cloud Run instances. Cloud Run can run multiple instances simultaneously.

**Reasoning:**
Redis is purpose-built for this use case. TTL-based key expiry handles lock lifecycle automatically. It is the industry-standard solution for distributed locking and deduplication.

---

## ADR-009 — Object Storage

**Status:** Accepted

**Context:**
The system needs to store binary artifacts: resume PDFs (base and tailored), browser screenshots, and email attachments. These are not appropriate for PostgreSQL storage.

**Decision:** Google Cloud Storage

**Alternatives Rejected:**
- **AWS S3** — Cross-cloud. Adds a second cloud vendor, separate credentials, and additional cost complexity. No technical advantage over GCS within a GCP-native stack.
- **Cloudflare R2** — Cross-cloud. Same objection as S3.
- **Storing files in PostgreSQL (BYTEA)** — Bloats the database. Complicates backups. Not designed for large binary file storage.
- **Local filesystem** — Cloud Run has an ephemeral filesystem. Files would be lost on instance replacement.

**Reasoning:**
GCS is natively integrated with the GCP project. IAM access is managed consistently with other services. Lifecycle policies automate file deletion without application-level cleanup logic.

---

## ADR-010 — Secrets Management

**Status:** Accepted

**Context:**
The system requires numerous sensitive credentials: PostgreSQL connection string, Gemini API key, Gmail OAuth tokens, Telegram session string, Redis URL. These must not be committed to the repository or embedded in container images.

**Decision:** Google Secret Manager

**Alternatives Rejected:**
- **Environment variables in plaintext** — Not secure. Cannot be rotated without redeployment. Not auditable.
- **HashiCorp Vault** — Powerful but significantly overengineered for a personal project on GCP. Requires a separate managed service.
- **AWS Secrets Manager** — Cross-cloud. No advantage over Google Secret Manager within a GCP stack.
- **`.env` file** — Development convenience only. Not suitable for production. Risk of accidental commit.

**Reasoning:**
Google Secret Manager integrates natively with Cloud Run (secrets can be injected as environment variables at deploy time). Access is controlled via IAM. Secret versions support rotation. Audit logging is built in.

---

## ADR-011 — Application Architecture (Monolith vs. Microservices)

**Status:** Accepted

**Context:**
This is a personal automation tool, not a public product. The team is one developer. The system has clear functional modules but low traffic and no need for independent scaling of individual components.

**Decision:** Modular monolith deployed as a single Cloud Run service

**Alternatives Rejected:**
- **Microservices (separate services per domain)** — Each service would require its own Cloud Run deployment, its own Cloud Tasks queue routing, its own IAM configuration, and its own logging setup. The operational overhead is disproportionate to the scale and team size.
- **Serverless functions per worker** — Cloud Functions execution limits make this unsuitable for Playwright workers. Also creates a proliferation of deployment units to manage.

**Reasoning:**
A modular monolith provides clean domain separation (enforced by the folder structure and import discipline) while remaining simple to deploy, debug, and operate. If a module ever needs to scale independently in the future, it can be extracted — but that problem does not exist today.

---

## ADR-012 — ORM and Migration Tool

**Status:** Accepted

**Context:**
The system requires a database access layer and a schema migration strategy.

**Decision:** SQLAlchemy 2 (async) + Alembic

**Alternatives Rejected:**
- **Tortoise ORM** — Less mature than SQLAlchemy. Smaller ecosystem. SQLAlchemy 2's async API is now first-class and there is no compelling reason to choose Tortoise.
- **Raw SQL (asyncpg)** — Writing raw SQL for all queries removes the abstraction layer that makes the codebase maintainable. SQLAlchemy's expression language provides a reasonable middle ground.
- **Peewee** — Synchronous ORM. Not suitable for an async FastAPI application.
- **Prisma (Python client)** — Experimental Python support. Not production-ready. JavaScript-first.
- **Flyway / Liquibase** — Java-based migration tools. Alembic is the native Python choice and integrates with SQLAlchemy models directly.

**Reasoning:**
SQLAlchemy 2 is the de facto standard Python ORM with first-class async support. Alembic is authored by the same team and has direct model introspection. Both are battle-tested in production environments.
