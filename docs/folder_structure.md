# Folder Structure

## Design Principles

- **Separation by domain, not by type.** Business domains (jobs, applications, resumes) are first-class organizational units. Generic types (models, schemas, services) are not top-level folders.
- **Flat inside modules.** Each domain module contains everything it owns. Deep nesting is avoided.
- **Shared infrastructure is explicit.** Code shared across domains lives in `core/` with a clear contract. Ad-hoc sharing between domain modules is discouraged.
- **Workers are thin.** Application workers contain only orchestration logic. Heavy logic lives in domain services.
- **Configuration lives at the root.** No configuration files are buried inside source directories.

---

## Complete Repository Structure

```
career-agent/
│
├── docs/                          # Project documentation (this folder)
│   ├── architecture.md
│   ├── database.md
│   ├── folder_structure.md
│   ├── technology_stack.md
│   ├── roadmap.md
│   └── decisions.md
│
├── src/                           # All application source code
│   │
│   ├── main.py                    # FastAPI app factory and startup
│   │
│   ├── config.py                  # Settings loaded from environment / Secret Manager
│   │
│   ├── core/                      # Cross-cutting infrastructure (no business logic)
│   │   ├── database.py            # SQLAlchemy engine, session factory
│   │   ├── redis.py               # Redis client factory
│   │   ├── storage.py             # GCS client wrapper
│   │   ├── secrets.py             # Google Secret Manager client
│   │   ├── tasks.py               # Google Cloud Tasks client wrapper
│   │   ├── logging.py             # Structured logging setup
│   │   └── exceptions.py          # Base exception classes
│   │
│   ├── jobs/                      # Job ingestion and enrichment domain
│   │   ├── models.py              # SQLAlchemy models: Job, JobRawMessage
│   │   ├── schemas.py             # Pydantic schemas for jobs
│   │   ├── service.py             # Job creation, deduplication, status updates
│   │   ├── enricher.py            # Gemini-based field extraction and scoring
│   │   ├── router_api.py          # FastAPI routes for job-related endpoints (if any)
│   │   └── repository.py          # DB query functions for jobs
│   │
│   ├── applications/              # Application lifecycle domain
│   │   ├── models.py              # SQLAlchemy models: Application, ApplicationEvent
│   │   ├── schemas.py             # Pydantic schemas
│   │   ├── service.py             # Application creation, state machine, event logging
│   │   ├── dispatcher.py          # Strategy dispatcher: selects and enqueues application strategies per job
│   │   ├── handlers.py            # FastAPI task handler endpoints (Cloud Tasks HTTP delivery targets)
│   │   └── repository.py          # DB query functions for applications
│   │
│   ├── workers/                   # Application strategy workers
│   │   ├── base.py                # Abstract base worker class
│   │   ├── portal_worker.py       # Playwright-based portal application worker
│   │   ├── form_worker.py         # Google Form submission worker
│   │   └── email_worker.py        # Gmail API cold email worker
│   │
│   ├── resumes/                   # Resume management domain
│   │   ├── models.py              # SQLAlchemy models: Resume, ApplicationResume
│   │   ├── schemas.py             # Pydantic schemas
│   │   ├── service.py             # Resume selection, tailoring orchestration
│   │   ├── generator.py           # Gemini-based resume tailoring logic
│   │   ├── renderer.py            # PDF generation from text/template
│   │   └── repository.py          # DB query functions for resumes
│   │
│   ├── telegram/                  # Telegram integration domain
│   │   ├── listener.py            # Telethon client, channel message listener
│   │   ├── notifier.py            # Outbound notifications to user
│   │   └── parser.py              # Raw message pre-processing before AI enrichment
│   │
│   ├── portals/                   # Portal-specific knowledge and configuration
│   │   ├── models.py              # SQLAlchemy model: PortalConfig
│   │   ├── registry.py            # Maps portal names to their handler classes
│   │   ├── base_portal.py         # Abstract portal handler interface
│   │   └── handlers/              # One file per supported portal
│   │       ├── linkedin.py
│   │       ├── indeed.py
│   │       └── greenhouse.py
│   │
│   ├── notifications/             # Notification domain
│   │   ├── models.py              # SQLAlchemy model: Notification
│   │   ├── schemas.py             # Pydantic schemas
│   │   ├── service.py             # Notification dispatch and status tracking
│   │   └── templates.py           # Notification message templates
│   │
│   ├── scheduler/                 # Periodic maintenance tasks
│   │   ├── cleanup.py             # Data retention cleanup logic
│   │   └── router_api.py          # FastAPI endpoints triggered by Cloud Scheduler
│   │
│   └── ai/                        # Shared AI client and prompt management
│       ├── client.py              # Gemini Flash client wrapper
│       └── prompts/               # Prompt templates as plain text or Python files
│           ├── job_extraction.py
│           ├── relevance_scoring.py
│           └── resume_tailoring.py
│
├── migrations/                    # Alembic migration scripts
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│
├── tests/                         # Test suite
│   ├── conftest.py                # Fixtures, test DB setup
│   ├── unit/                      # Unit tests per domain
│   │   ├── test_jobs.py
│   │   ├── test_applications.py
│   │   ├── test_resumes.py
│   │   └── test_ai.py
│   └── integration/               # Integration tests (real DB, mocked external)
│       ├── test_job_pipeline.py
│       └── test_application_pipeline.py
│
├── scripts/                       # One-off operational scripts (not in source path)
│   ├── seed_portal_configs.py     # Load initial portal configs into DB
│   └── upload_base_resume.py     # Upload base resume to GCS
│
└── assets/                        # Static assets for resume generation
    └── resume_template.html       # HTML template for PDF rendering
```

---

## Folder Explanations

### `src/`
All Python source code lives here. Keeping source separate from the project root avoids polluting the namespace and makes the `PYTHONPATH` explicit.

### `src/core/`
Infrastructure plumbing only. No business logic. Any module in the project may import from `core/`, but `core/` never imports from domain modules. This prevents circular dependencies and keeps infrastructure swappable.

### `src/jobs/`
Owns everything related to detecting, parsing, storing, and enriching job postings. The enricher calls the AI client; the service manages lifecycle state. Nothing outside this domain should directly manipulate job DB records.

### `src/applications/`
Owns the application lifecycle state machine. `dispatcher.py` decides which worker strategies to invoke based on detected URLs and email fields in the job record. `handlers.py` contains the FastAPI endpoints that receive Cloud Tasks HTTP deliveries. Application event logging is handled here, not in the workers themselves.

### `src/workers/`
Thin orchestration layer. Each worker receives an application ID, delegates to domain services (resume, portal), and reports the outcome back to the application service. Workers do not contain portal-specific knowledge — that lives in `src/portals/`.

### `src/resumes/`
Owns resume selection, AI tailoring, PDF rendering, and Cloud Storage upload. The `generator.py` calls the AI client; the `renderer.py` handles PDF concerns. The service orchestrates the full flow.

### `src/telegram/`
Two distinct responsibilities: listening for incoming job messages (listener) and sending notifications to the user (notifier). These are kept in the same domain because they share the Telethon client.

### `src/portals/`
Encapsulates all portal-specific knowledge behind a common interface defined in `base_portal.py`. Adding a new portal requires only creating a new handler file and registering it in `registry.py`. No other code needs to change.

### `src/ai/`
Central point for all Gemini API calls. Prompt templates are versioned here. This isolation means prompt engineering changes never touch business logic files.

### `src/scheduler/`
Periodic maintenance jobs (cleanup, re-queuing stalled tasks). Triggered by Cloud Scheduler via HTTP, consistent with how all workers are triggered.

### `migrations/`
Alembic migration history. Migration files are never edited after creation. Schema changes always produce a new migration.

### `tests/`
Split into unit (fast, no external dependencies) and integration (requires a test database). The `conftest.py` at the root provides shared fixtures for both layers.

### `scripts/`
Operational one-off scripts for setup tasks. Not imported by the application. Executed manually during provisioning.

---

## Growth Guidance

| Scenario | Action |
|---|---|
| New portal added | Add handler to `src/portals/handlers/`, register in `registry.py` |
| New AI capability | Add prompt to `src/ai/prompts/`, add method to relevant domain service |
| New notification channel (e.g. email alerts) | Add sender to `src/notifications/service.py` |
| New job source (e.g. RSS feed) | Add new listener in `src/telegram/` or create `src/sources/` if needed |
| Schema change | Add new Alembic migration in `migrations/versions/` |
| New periodic job | Add to `src/scheduler/`, register Cloud Scheduler trigger |
