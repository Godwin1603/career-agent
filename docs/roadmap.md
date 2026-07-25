# Roadmap

## Phase 1 — Foundation

**Objective:** Establish the project skeleton, local development environment, and core infrastructure plumbing. Every subsequent phase builds on top of this.

**Deliverables:**
- Repository initialized with the folder structure defined in `folder_structure.md`
- `src/config.py` reading from environment variables with Pydantic v2 `BaseSettings`
- `src/core/logging.py` — structured JSON logging configured for Cloud Run
- `src/core/exceptions.py` — base exception hierarchy
- `src/main.py` — FastAPI app factory with health check endpoint
- Development environment documented and reproducible (`pyproject.toml`, `requirements.txt` or `uv.lock`)
- Google Secret Manager client wired to config loading

**Completion Criteria:**
- `uvicorn src.main:app` starts without errors
- Health check endpoint returns 200
- Secrets are loaded from the environment (or Secret Manager in staging)
- Logging outputs structured JSON

---

## Phase 2 — Database

**Objective:** Stand up PostgreSQL connectivity, define all SQLAlchemy models, and produce the initial Alembic migration.

**Deliverables:**
- `src/core/database.py` — async SQLAlchemy engine and session factory (no models)
- SQLAlchemy models for all tables defined in `database.md`:
  - `jobs`, `job_raw_messages`
  - `applications`, `application_events`
  - `resumes`, `application_resumes`
  - `notifications`
  - `portal_configs`
  - `task_log`
- Alembic configured and `migrations/versions/` directory populated with the initial migration
- Repository layer for each domain (query functions, no business logic)

**Completion Criteria:**
- `alembic upgrade head` applies all migrations against a clean Neon database without errors
- All SQLAlchemy models can be imported and queried via async sessions
- `alembic downgrade base` cleanly reverses all migrations

---

## Phase 3 — Infrastructure Clients

**Objective:** Build and test all external service clients before any business logic depends on them.

**Deliverables:**
- `src/core/redis.py` — async Redis client with connection pooling
- `src/core/storage.py` — GCS client wrapper (upload, download, check existence, delete)
- `src/core/tasks.py` — Google Cloud Tasks client (enqueue task, cancel task)
- `src/core/secrets.py` — Secret Manager client (fetch secret by name)
- `src/ai/client.py` — Gemini Flash client (text generation, structured JSON output)
- All clients tested in isolation with mocked external calls

**Completion Criteria:**
- Each client can be instantiated and invoked in isolation
- Unit tests pass for each client with mocked responses
- Redis ping succeeds against a real Redis instance
- GCS upload and download work against a real GCS bucket in the dev project

---

## Phase 4 — AI Engine

**Objective:** Implement all prompt templates and validate that Gemini reliably extracts structured data from real job postings.

**Deliverables:**
- `src/ai/prompts/job_extraction.py` — extracts company, role, location, URLs, email, salary from raw text
- `src/ai/prompts/relevance_scoring.py` — scores job relevance (0–100) with reasoning
- `src/ai/prompts/resume_tailoring.py` — adapts base resume text to a specific job description
- Prompt outputs validated via Pydantic schemas
- Test suite with a set of real anonymized job posting samples

**Completion Criteria:**
- Extraction prompt correctly parses at least 20 representative job posting samples
- Relevance scoring produces consistent, sensible results
- Resume tailoring produces a meaningfully differentiated output vs. the base resume
- All Pydantic validation passes on AI outputs without manual intervention

---

## Phase 5 — Telegram Listener

**Objective:** Connect to the private Telegram channel, detect new job messages, and persist them.

**Deliverables:**
- `src/telegram/listener.py` — Telethon client authenticated via session string stored in Secret Manager
- `src/telegram/parser.py` — minimal pre-processing of raw text before AI enrichment
- `src/jobs/service.py` — deduplication check (Redis) and `job_raw_messages` record creation
- Integration with the job enrichment queue: new message → Redis dedup check → store raw → enqueue enrichment task
- `src/telegram/notifier.py` — minimal working notifier: sends a plain Telegram message via Telethon. This is intentionally simple — the full notification service with templates, entity references, and retry logic is built in Phase 9. The stub is functional enough to be used in Phase 8 for failure and success alerts during worker development and testing.

**Completion Criteria:**
- Listener connects to the channel and fires on new messages during a live test
- Duplicate messages (same Telegram message ID) are silently ignored
- New messages produce a `job_raw_messages` record in PostgreSQL
- An enrichment task is enqueued in Cloud Tasks for each new message

---

## Phase 6 — Job Enrichment Pipeline

**Objective:** Process raw job messages through the AI engine to produce structured job records and route them to the correct application strategy.

**Deliverables:**
- FastAPI endpoint: `POST /tasks/enrich-job` (Cloud Tasks delivery target)
- `src/jobs/enricher.py` — calls AI engine, validates output, populates `jobs` table
- `src/applications/dispatcher.py` — application strategy selection based on detected URLs and email
- Task dispatch to `portal-application`, `form-application`, or `email-application` queues
- Jobs below the relevance threshold are marked `skipped`

**Completion Criteria:**
- A raw message record triggers enrichment and produces a populated `jobs` record
- Application tasks are correctly enqueued based on detected strategy
- Sub-threshold jobs are marked skipped with no further processing
- Redis lock prevents duplicate enrichment if the same task is delivered twice

---

## Phase 7 — Resume Manager

**Objective:** Implement the full resume selection, tailoring, and storage pipeline.

**Deliverables:**
- `src/resumes/service.py` — orchestrates resume selection and tailoring
- `src/resumes/generator.py` — calls AI engine for tailoring
- `src/resumes/renderer.py` — generates PDF from tailored resume text
- GCS upload and caching (skip regeneration if tailored resume already exists for this job)
- `resumes` and `application_resumes` DB records created per application

**Completion Criteria:**
- A base resume uploaded to GCS is retrieved and tailored for a test job description
- The tailored PDF is generated and uploaded to GCS
- Subsequent calls for the same job return the cached GCS file without calling Gemini again
- DB records correctly reflect which resume was used for which application

---

## Phase 8 — Application Workers

**Objective:** Implement the three application strategies as Cloud Tasks-triggered workers.

**Deliverables:**

**Portal Worker (Playwright)**
- FastAPI endpoint: `POST /tasks/apply-portal`
- `src/workers/portal_worker.py`
- `src/portals/base_portal.py` — abstract interface
- `src/portals/registry.py` — portal name to handler mapping
- First portal handler (e.g., Greenhouse or LinkedIn Easy Apply)

**Form Worker**
- FastAPI endpoint: `POST /tasks/apply-form`
- `src/workers/form_worker.py`
- Google Form field detection and submission via Playwright

**Email Worker**
- FastAPI endpoint: `POST /tasks/apply-email`
- `src/workers/email_worker.py`
- Gmail API integration: compose, attach resume PDF, send

**Completion Criteria:**
- Each worker can complete a successful application end-to-end in a controlled test
- Failure handling: failed attempts update `applications` with error details
- Redis lock prevents duplicate execution per application
- Screenshots are uploaded to GCS on failure for debugging
- Worker outcomes (success and failure) trigger a Telegram notification via the Phase 5 stub notifier, providing a feedback channel during live testing without requiring Phase 9 to be complete

---

## Phase 9 — Notifications

**Objective:** Deliver reliable, informative Telegram notifications to the user for every meaningful system event.

**Deliverables:**
- FastAPI endpoint: `POST /tasks/notify`
- `src/notifications/service.py` — notification dispatch via Telethon
- `src/notifications/templates.py` — message templates for all notification types
- `notifications` table records created and updated on delivery status

**Completion Criteria:**
- User receives a Telegram message within 30 seconds of an application outcome
- All notification types (success, failure, skipped, manual-review-needed) are tested
- Failed notification delivery is retried via Cloud Tasks

---

## Phase 10 — Scheduler and Maintenance

**Objective:** Implement automated data cleanup and operational health checks.

**Deliverables:**
- `src/scheduler/cleanup.py` — retention-based deletion for all tables per policy in `database.md`
- FastAPI endpoint: `POST /scheduler/cleanup` (triggered by Cloud Scheduler)
- GCS lifecycle policies defined and documented
- Basic operational dashboard or log query to inspect system health

**Completion Criteria:**
- Cleanup tasks run successfully against a database with test data
- Expired records are deleted; non-expired records are preserved
- Cloud Scheduler trigger fires daily and produces a log entry confirming completion

---

## Phase 11 — Hardening and Production Readiness

**Objective:** Prepare the system for reliable unattended operation.

**Deliverables:**
- Comprehensive error handling audit across all workers
- Redis lock TTL review and edge case testing
- Cloud Tasks retry configuration validated for each queue
- Integration test suite covering the full pipeline end-to-end
- Rate limiting per portal enforced
- Manual runbook documented for common failure scenarios

**Completion Criteria:**
- Full pipeline runs end-to-end without manual intervention on at least 10 consecutive real job postings
- No duplicate applications observed across 100 test runs
- All Cloud Tasks queues have been stress-tested with intentional transient failures
- All secrets are sourced from Secret Manager (no plaintext secrets in environment)

---

## Phase 12 — Additional Portals

**Objective:** Expand portal coverage based on the most common portals appearing in the Telegram channel.

**Deliverables:**
- Additional portal handlers added to `src/portals/handlers/`
- Each handler tested against a real (non-consequential) application
- `portal_configs` DB table populated for each new portal

**Completion Criteria:**
- At least 3 portal handlers operational
- Portal registry correctly routes applications by detected portal name
- New portals can be added without modifying any existing code outside `portals/`
