"""
Unit tests for Phase 3 repository layer.

These tests exercise the repository classes using SQLAlchemy's in-memory
SQLite engine (via aiosqlite) for fast, offline execution — no running
PostgreSQL is required.

Coverage:
  - BaseRepository: create, get_by_id, get_one, list_all, list_paginated,
                    exists, count, update, delete, EntityNotFound, RepositoryError
  - Pagination / PaginatedResult value objects
  - JobRawMessageRepository
  - JobRepository
  - ApplicationRepository / ApplicationEventRepository
  - ResumeRepository / ApplicationResumeRepository
  - NotificationRepository
  - PortalConfigRepository
  - TaskLogRepository
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import src.core.model_registry  # noqa: F401 — register all models on Base.metadata
from src.applications.models import Application, ApplicationEvent
from src.applications.repository import (
    ApplicationEventRepository,
    ApplicationRepository,
)
from src.core.database import Base
from src.core.enums import (
    ApplicationStatus,
    ApplicationStrategy,
    JobStatus,
    NotificationDeliveryStatus,
    NotificationType,
    RawMessageStatus,
    ResumeLabel,
    TaskStatus,
    TaskType,
)
from src.core.exceptions import EntityNotFound, RepositoryError
from src.core.repository import PaginatedResult, Pagination
from src.core.task_log import TaskLog
from src.core.task_log_repository import TaskLogRepository
from src.jobs.models import Job, JobRawMessage
from src.jobs.repository import JobRawMessageRepository, JobRepository
from src.notifications.models import Notification
from src.notifications.repository import NotificationRepository
from src.portals.models import PortalConfig
from src.portals.repository import PortalConfigRepository
from src.resumes.models import ApplicationResume, Resume
from src.resumes.repository import ApplicationResumeRepository, ResumeRepository

# ---------------------------------------------------------------------------
# In-memory test engine (aiosqlite — no PostgreSQL required)
# ---------------------------------------------------------------------------
# We use aiosqlite with SQLite for unit tests. A few SQLite-specific notes:
#   - We enable PRAGMA foreign_keys=ON so FK constraints are enforced.
#   - PostgreSQL-specific types (UUID, JSONB, Enum) are automatically mapped
#     to compatible SQLite equivalents by SQLAlchemy.
#   - Enum values are stored as VARCHAR on SQLite.


TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture(scope="function")
async def engine():
    """Create a fresh in-memory SQLite engine per test function.

    SQLite does not support PostgreSQL-specific types (JSONB, UUID as native
    types, etc.). We build a shallow copy of Base.metadata and replace JSONB
    columns with sa.JSON so SQLite can render the DDL without touching the
    shared Base.metadata used by the Phase 2 model tests.
    """

    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB

    eng = create_async_engine(TEST_DATABASE_URL, echo=False)

    # Enable FK enforcement for SQLite
    @event.listens_for(eng.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Build a SQLite-compatible copy of the metadata:
    # swap postgresql.JSONB → sa.JSON() on every JSONB column.
    # We operate directly on Base.metadata because SQLAlchemy MetaData objects
    # are not trivially deep-copyable; instead we just replace column types
    # temporarily and restore them after create_all.
    jsonb_columns: list[sa.Column] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                jsonb_columns.append(column)
                column.type = sa.JSON()

    try:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        # Restore original JSONB types so Phase 2 model tests are unaffected
        for column in jsonb_columns:
            column.type = JSONB()

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await eng.dispose()


@pytest_asyncio.fixture(scope="function")
async def session(engine):
    """Provide a transactional async session per test, rolled back on teardown."""
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with async_session_maker() as sess:
        yield sess
        await sess.rollback()


# ---------------------------------------------------------------------------
# Helpers — factory functions for clean test data
# ---------------------------------------------------------------------------


def make_raw_message(
    telegram_message_id: int = 1001,
    channel_id: int = -100_000_000_001,
    raw_text: str = "Senior Python Engineer at Acme Corp — apply at careers.acme.com",
    status: RawMessageStatus = RawMessageStatus.pending,
) -> JobRawMessage:
    return JobRawMessage(
        id=uuid.uuid4(),
        telegram_message_id=telegram_message_id,
        channel_id=channel_id,
        raw_text=raw_text,
        status=status,
    )


def make_job(
    raw_message_id: uuid.UUID | None = None,
    company_name: str = "Acme Corp",
    role_title: str = "Senior Python Engineer",
    status: JobStatus = JobStatus.pending,
    relevance_score: float | None = 85.0,
    detected_portal: str | None = "linkedin",
) -> Job:
    return Job(
        id=uuid.uuid4(),
        raw_message_id=raw_message_id,
        company_name=company_name,
        role_title=role_title,
        status=status,
        relevance_score=relevance_score,
        detected_portal=detected_portal,
    )


def make_application(
    job_id: uuid.UUID,
    strategy: ApplicationStrategy = ApplicationStrategy.portal,
    status: ApplicationStatus = ApplicationStatus.pending,
) -> Application:
    return Application(
        id=uuid.uuid4(),
        job_id=job_id,
        strategy=strategy,
        status=status,
        attempt_count=0,
    )


def make_application_event(
    application_id: uuid.UUID,
    event_type: str = "status_changed",
) -> ApplicationEvent:
    return ApplicationEvent(
        id=uuid.uuid4(),
        application_id=application_id,
        event_type=event_type,
        event_payload={"from": "pending", "to": "in_progress"},
    )


def make_resume(
    label: ResumeLabel = ResumeLabel.base,
    job_id: uuid.UUID | None = None,
    gcs_path: str = "resumes/base/resume.pdf",
    content_hash: str = "abc123" + "0" * 58,
) -> Resume:
    return Resume(
        id=uuid.uuid4(),
        label=label,
        job_id=job_id,
        gcs_path=gcs_path,
        content_hash=content_hash,
    )


def make_notification(
    job_id: uuid.UUID | None = None,
    application_id: uuid.UUID | None = None,
    notification_type: NotificationType = NotificationType.new_job_found,
    delivery_status: NotificationDeliveryStatus = NotificationDeliveryStatus.pending,
) -> Notification:
    return Notification(
        id=uuid.uuid4(),
        job_id=job_id,
        application_id=application_id,
        notification_type=notification_type,
        message_content="Test notification message",
        delivery_status=delivery_status,
    )


def make_portal_config(
    portal_name: str = "linkedin",
    is_enabled: bool = True,
) -> PortalConfig:
    return PortalConfig(
        id=uuid.uuid4(),
        portal_name=portal_name,
        portal_base_url=f"https://{portal_name}.com",
        is_enabled=is_enabled,
    )


def make_task_log(
    entity_id: str | None = None,
    task_type: TaskType = TaskType.job_enrichment,
    status: TaskStatus = TaskStatus.pending,
    cloud_task_name: str | None = None,
) -> TaskLog:
    _entity_id = entity_id or str(uuid.uuid4())
    return TaskLog(
        id=uuid.uuid4(),
        cloud_task_name=cloud_task_name or f"projects/p/queues/q/tasks/{uuid.uuid4()}",
        task_type=task_type,
        entity_id=_entity_id,
        status=status,
    )


# ===========================================================================
# Pagination / PaginatedResult tests
# ===========================================================================


def test_pagination_valid():
    p = Pagination(page=2, page_size=10)
    assert p.offset == 10
    assert p.limit == 10


def test_pagination_first_page():
    p = Pagination(page=1, page_size=25)
    assert p.offset == 0
    assert p.limit == 25


def test_pagination_invalid_page():
    with pytest.raises(ValueError, match="page must be >= 1"):
        Pagination(page=0)


def test_pagination_invalid_page_size():
    with pytest.raises(ValueError, match="page_size must be between"):
        Pagination(page_size=0)


def test_pagination_page_size_max():
    with pytest.raises(ValueError):
        Pagination(page_size=501)


def test_paginated_result_pages():
    p = Pagination(page=1, page_size=10)
    r: PaginatedResult = PaginatedResult(items=[], total=35, pagination=p)
    assert r.pages == 4


def test_paginated_result_has_next():
    p = Pagination(page=1, page_size=10)
    r = PaginatedResult(items=[], total=25, pagination=p)
    assert r.has_next is True
    assert r.has_prev is False


def test_paginated_result_last_page():
    p = Pagination(page=3, page_size=10)
    r = PaginatedResult(items=[], total=25, pagination=p)
    assert r.has_next is False
    assert r.has_prev is True


# ===========================================================================
# BaseRepository via JobRawMessageRepository (concrete subclass)
# ===========================================================================


@pytest.mark.asyncio
async def test_create_and_get_by_id(session):
    repo = JobRawMessageRepository(session)
    msg = make_raw_message()
    created = await repo.create(msg)
    assert created.id == msg.id

    fetched = await repo.get_by_id(created.id)
    assert fetched.telegram_message_id == msg.telegram_message_id


@pytest.mark.asyncio
async def test_get_by_id_not_found_raises(session):
    repo = JobRawMessageRepository(session)
    with pytest.raises(EntityNotFound) as exc_info:
        await repo.get_by_id(uuid.uuid4())
    assert "JobRawMessage" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_by_id_or_none_returns_none(session):
    repo = JobRawMessageRepository(session)
    result = await repo.get_by_id_or_none(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_one(session):
    repo = JobRawMessageRepository(session)
    msg = make_raw_message(telegram_message_id=9999)
    await repo.create(msg)
    fetched = await repo.get_one(JobRawMessage.telegram_message_id == 9999)
    assert fetched.id == msg.id


@pytest.mark.asyncio
async def test_get_one_not_found_raises(session):
    repo = JobRawMessageRepository(session)
    with pytest.raises(EntityNotFound):
        await repo.get_one(JobRawMessage.telegram_message_id == -1)


@pytest.mark.asyncio
async def test_get_one_or_none(session):
    repo = JobRawMessageRepository(session)
    result = await repo.get_one_or_none(JobRawMessage.telegram_message_id == -99)
    assert result is None


@pytest.mark.asyncio
async def test_list_all(session):
    repo = JobRawMessageRepository(session)
    await repo.create(make_raw_message(telegram_message_id=1))
    await repo.create(make_raw_message(telegram_message_id=2))
    all_msgs = await repo.list_all()
    assert len(all_msgs) == 2


@pytest.mark.asyncio
async def test_list_all_with_filter(session):
    repo = JobRawMessageRepository(session)
    await repo.create(
        make_raw_message(telegram_message_id=1, status=RawMessageStatus.pending)
    )
    await repo.create(
        make_raw_message(telegram_message_id=2, status=RawMessageStatus.processed)
    )
    pending = await repo.list_all(JobRawMessage.status == RawMessageStatus.pending)
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_list_paginated(session):
    repo = JobRawMessageRepository(session)
    for i in range(5):
        await repo.create(make_raw_message(telegram_message_id=100 + i))
    page = Pagination(page=1, page_size=3)
    result = await repo.list_paginated(page)
    assert len(result.items) == 3
    assert result.total == 5
    assert result.pages == 2
    assert result.has_next is True


@pytest.mark.asyncio
async def test_list_paginated_page_2(session):
    repo = JobRawMessageRepository(session)
    for i in range(5):
        await repo.create(make_raw_message(telegram_message_id=200 + i))
    page = Pagination(page=2, page_size=3)
    result = await repo.list_paginated(page)
    assert len(result.items) == 2
    assert result.has_next is False
    assert result.has_prev is True


@pytest.mark.asyncio
async def test_exists_true(session):
    repo = JobRawMessageRepository(session)
    msg = make_raw_message(telegram_message_id=777)
    await repo.create(msg)
    assert await repo.exists(JobRawMessage.telegram_message_id == 777) is True


@pytest.mark.asyncio
async def test_exists_false(session):
    repo = JobRawMessageRepository(session)
    assert await repo.exists(JobRawMessage.telegram_message_id == 999) is False


@pytest.mark.asyncio
async def test_count(session):
    repo = JobRawMessageRepository(session)
    await repo.create(make_raw_message(telegram_message_id=1))
    await repo.create(make_raw_message(telegram_message_id=2))
    assert await repo.count() == 2


@pytest.mark.asyncio
async def test_update(session):
    repo = JobRawMessageRepository(session)
    msg = await repo.create(make_raw_message())
    updated = await repo.update(msg, status=RawMessageStatus.processed)
    assert updated.status == RawMessageStatus.processed


@pytest.mark.asyncio
async def test_delete(session):
    repo = JobRawMessageRepository(session)
    msg = await repo.create(make_raw_message())
    entity_id = msg.id
    await repo.delete(msg)
    result = await repo.get_by_id_or_none(entity_id)
    assert result is None


@pytest.mark.asyncio
async def test_delete_by_id(session):
    repo = JobRawMessageRepository(session)
    msg = await repo.create(make_raw_message())
    entity_id = msg.id
    await repo.delete_by_id(entity_id)
    assert await repo.get_by_id_or_none(entity_id) is None


@pytest.mark.asyncio
async def test_delete_by_id_not_found(session):
    repo = JobRawMessageRepository(session)
    with pytest.raises(EntityNotFound):
        await repo.delete_by_id(uuid.uuid4())


# ===========================================================================
# JobRawMessageRepository — domain-specific tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_by_telegram_ids(session):
    repo = JobRawMessageRepository(session)
    msg = await repo.create(
        make_raw_message(telegram_message_id=5555, channel_id=-100_001)
    )
    result = await repo.get_by_telegram_ids(5555, -100_001)
    assert result is not None
    assert result.id == msg.id


@pytest.mark.asyncio
async def test_get_by_telegram_ids_not_found(session):
    repo = JobRawMessageRepository(session)
    result = await repo.get_by_telegram_ids(9999, -1)
    assert result is None


@pytest.mark.asyncio
async def test_exists_by_telegram_ids(session):
    repo = JobRawMessageRepository(session)
    await repo.create(make_raw_message(telegram_message_id=6000, channel_id=-100_002))
    assert await repo.exists_by_telegram_ids(6000, -100_002) is True
    assert await repo.exists_by_telegram_ids(6000, -100_999) is False


@pytest.mark.asyncio
async def test_list_by_status(session):
    repo = JobRawMessageRepository(session)
    await repo.create(
        make_raw_message(telegram_message_id=1, status=RawMessageStatus.pending)
    )
    await repo.create(
        make_raw_message(telegram_message_id=2, status=RawMessageStatus.pending)
    )
    await repo.create(
        make_raw_message(telegram_message_id=3, status=RawMessageStatus.processed)
    )
    pending = await repo.list_by_status(RawMessageStatus.pending)
    assert len(pending) == 2


@pytest.mark.asyncio
async def test_list_older_than_raw_messages(session):
    repo = JobRawMessageRepository(session)
    msg = await repo.create(make_raw_message())
    # All messages are "older than" the future
    cutoff = datetime(2099, 1, 1, tzinfo=timezone.utc)
    results = await repo.list_older_than(cutoff)
    assert any(r.id == msg.id for r in results)


# ===========================================================================
# JobRepository tests
# ===========================================================================


@pytest.mark.asyncio
async def test_job_create_and_get(session):
    repo = JobRepository(session)
    job = await repo.create(make_job())
    fetched = await repo.get_by_id(job.id)
    assert fetched.company_name == "Acme Corp"


@pytest.mark.asyncio
async def test_job_get_by_status(session):
    repo = JobRepository(session)
    await repo.create(make_job(status=JobStatus.pending))
    await repo.create(make_job(status=JobStatus.enriched))
    pending = await repo.get_by_status(JobStatus.pending)
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_job_list_active(session):
    repo = JobRepository(session)
    # Active = enriched + no expiry
    await repo.create(make_job(status=JobStatus.enriched))
    await repo.create(make_job(status=JobStatus.pending))
    active = await repo.list_active()
    assert len(active) == 1


@pytest.mark.asyncio
async def test_job_list_expired(session):

    repo = JobRepository(session)
    past = datetime(2020, 1, 1, tzinfo=timezone.utc)
    job = make_job(status=JobStatus.enriched)
    job.expires_at = past
    await repo.create(job)
    # Cutoff is now, so anything before now is expired
    cutoff = datetime.now(tz=timezone.utc)
    expired = await repo.list_expired(cutoff)
    assert any(j.id == job.id for j in expired)


@pytest.mark.asyncio
async def test_job_list_by_portal(session):
    repo = JobRepository(session)
    await repo.create(make_job(detected_portal="linkedin"))
    await repo.create(make_job(detected_portal="greenhouse"))
    linkedin_jobs = await repo.list_by_portal("linkedin")
    assert len(linkedin_jobs) == 1


@pytest.mark.asyncio
async def test_job_list_above_relevance(session):
    repo = JobRepository(session)
    await repo.create(make_job(relevance_score=90.0))
    await repo.create(make_job(relevance_score=40.0))
    high = await repo.list_above_relevance(70.0)
    assert len(high) == 1
    assert high[0].relevance_score == 90.0


@pytest.mark.asyncio
async def test_job_count_by_status(session):
    repo = JobRepository(session)
    await repo.create(make_job(status=JobStatus.pending))
    await repo.create(make_job(status=JobStatus.pending))
    await repo.create(make_job(status=JobStatus.enriched))
    assert await repo.count_by_status(JobStatus.pending) == 2
    assert await repo.count_by_status(JobStatus.enriched) == 1


@pytest.mark.asyncio
async def test_job_list_paginated_by_status(session):
    repo = JobRepository(session)
    for _ in range(4):
        await repo.create(make_job(status=JobStatus.pending))
    page = Pagination(page=1, page_size=2)
    result = await repo.list_paginated_by_status(JobStatus.pending, page)
    assert result.total == 4
    assert len(result.items) == 2


# ===========================================================================
# ApplicationRepository tests
# ===========================================================================


@pytest.mark.asyncio
async def test_application_create_and_get(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    job = await job_repo.create(make_job())
    app = await app_repo.create(make_application(job_id=job.id))
    fetched = await app_repo.get_by_id(app.id)
    assert fetched.job_id == job.id


@pytest.mark.asyncio
async def test_get_by_job_and_strategy(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    job = await job_repo.create(make_job())
    app = await app_repo.create(
        make_application(job_id=job.id, strategy=ApplicationStrategy.email)
    )
    result = await app_repo.get_by_job_and_strategy(job.id, ApplicationStrategy.email)
    assert result is not None
    assert result.id == app.id


@pytest.mark.asyncio
async def test_get_by_job_and_strategy_none(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    job = await job_repo.create(make_job())
    result = await app_repo.get_by_job_and_strategy(job.id, ApplicationStrategy.portal)
    assert result is None


@pytest.mark.asyncio
async def test_exists_for_job_and_strategy(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    job = await job_repo.create(make_job())
    await app_repo.create(
        make_application(job_id=job.id, strategy=ApplicationStrategy.form)
    )
    assert (
        await app_repo.exists_for_job_and_strategy(job.id, ApplicationStrategy.form)
        is True
    )
    assert (
        await app_repo.exists_for_job_and_strategy(job.id, ApplicationStrategy.portal)
        is False
    )


@pytest.mark.asyncio
async def test_list_by_job(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    job = await job_repo.create(make_job())
    await app_repo.create(
        make_application(job_id=job.id, strategy=ApplicationStrategy.portal)
    )
    await app_repo.create(
        make_application(job_id=job.id, strategy=ApplicationStrategy.email)
    )
    apps = await app_repo.list_by_job(job.id)
    assert len(apps) == 2


@pytest.mark.asyncio
async def test_application_list_by_status(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    job = await job_repo.create(make_job())
    await app_repo.create(
        make_application(job_id=job.id, status=ApplicationStatus.pending)
    )
    await app_repo.create(
        make_application(
            job_id=job.id,
            strategy=ApplicationStrategy.email,
            status=ApplicationStatus.success,
        )
    )
    pending = await app_repo.list_by_status(ApplicationStatus.pending)
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_list_stale_in_progress(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    job = await job_repo.create(make_job())
    app = await app_repo.create(
        make_application(job_id=job.id, status=ApplicationStatus.in_progress)
    )
    cutoff = datetime(2099, 1, 1, tzinfo=timezone.utc)
    stale = await app_repo.list_stale_in_progress(cutoff)
    assert any(s.id == app.id for s in stale)


@pytest.mark.asyncio
async def test_application_count_by_status(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    job = await job_repo.create(make_job())
    await app_repo.create(
        make_application(job_id=job.id, status=ApplicationStatus.success)
    )
    await app_repo.create(
        make_application(
            job_id=job.id,
            strategy=ApplicationStrategy.email,
            status=ApplicationStatus.success,
        )
    )
    assert await app_repo.count_by_status(ApplicationStatus.success) == 2


@pytest.mark.asyncio
async def test_application_list_paginated(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    for _ in range(3):
        job = await job_repo.create(make_job())
        await app_repo.create(
            make_application(job_id=job.id, status=ApplicationStatus.pending)
        )
    page = Pagination(page=1, page_size=2)
    result = await app_repo.list_paginated_by_status(ApplicationStatus.pending, page)
    assert result.total == 3
    assert len(result.items) == 2


# ===========================================================================
# ApplicationEventRepository tests
# ===========================================================================


@pytest.mark.asyncio
async def test_event_create_and_list(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    evt_repo = ApplicationEventRepository(session)

    job = await job_repo.create(make_job())
    app = await app_repo.create(make_application(job_id=job.id))
    evt = await evt_repo.create(make_application_event(application_id=app.id))
    events = await evt_repo.list_by_application(app.id)
    assert len(events) == 1
    assert events[0].id == evt.id


@pytest.mark.asyncio
async def test_event_list_by_type(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    evt_repo = ApplicationEventRepository(session)

    job = await job_repo.create(make_job())
    app = await app_repo.create(make_application(job_id=job.id))
    await evt_repo.create(make_application_event(app.id, event_type="status_changed"))
    await evt_repo.create(make_application_event(app.id, event_type="error_recorded"))
    status_events = await evt_repo.list_by_event_type(app.id, "status_changed")
    assert len(status_events) == 1


@pytest.mark.asyncio
async def test_event_count(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    evt_repo = ApplicationEventRepository(session)

    job = await job_repo.create(make_job())
    app = await app_repo.create(make_application(job_id=job.id))
    await evt_repo.create(make_application_event(app.id))
    await evt_repo.create(make_application_event(app.id))
    assert await evt_repo.count_by_application(app.id) == 2


# ===========================================================================
# ResumeRepository tests
# ===========================================================================


@pytest.mark.asyncio
async def test_get_base_resume(session):
    repo = ResumeRepository(session)
    base = await repo.create(make_resume(label=ResumeLabel.base))
    result = await repo.get_base_resume()
    assert result is not None
    assert result.id == base.id


@pytest.mark.asyncio
async def test_get_base_resume_none(session):
    repo = ResumeRepository(session)
    result = await repo.get_base_resume()
    assert result is None


@pytest.mark.asyncio
async def test_get_tailored_for_job(session):
    job_repo = JobRepository(session)
    resume_repo = ResumeRepository(session)
    job = await job_repo.create(make_job())
    tailored = await resume_repo.create(
        make_resume(
            label=ResumeLabel.tailored, job_id=job.id, gcs_path="resumes/tailored.pdf"
        )
    )
    result = await resume_repo.get_tailored_for_job(job.id)
    assert result is not None
    assert result.id == tailored.id


@pytest.mark.asyncio
async def test_get_tailored_for_job_none(session):
    repo = ResumeRepository(session)
    result = await repo.get_tailored_for_job(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_get_by_content_hash(session):
    repo = ResumeRepository(session)
    r = await repo.create(make_resume(content_hash="a" * 64))
    result = await repo.get_by_content_hash("a" * 64)
    assert result is not None
    assert result.id == r.id


@pytest.mark.asyncio
async def test_list_by_label(session):
    job_repo = JobRepository(session)
    resume_repo = ResumeRepository(session)
    job = await job_repo.create(make_job())
    await resume_repo.create(make_resume(label=ResumeLabel.base))
    await resume_repo.create(
        make_resume(
            label=ResumeLabel.tailored,
            job_id=job.id,
            gcs_path="t.pdf",
            content_hash="b" * 64,
        )
    )
    base_resumes = await resume_repo.list_by_label(ResumeLabel.base)
    assert len(base_resumes) == 1


# ===========================================================================
# ApplicationResumeRepository tests
# ===========================================================================


@pytest.mark.asyncio
async def test_application_resume_link(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    resume_repo = ResumeRepository(session)
    ar_repo = ApplicationResumeRepository(session)

    job = await job_repo.create(make_job())
    app = await app_repo.create(make_application(job_id=job.id))
    resume = await resume_repo.create(make_resume())

    link = ApplicationResume(application_id=app.id, resume_id=resume.id)
    await ar_repo.create(link)

    assert await ar_repo.exists_for_application(app.id) is True


@pytest.mark.asyncio
async def test_get_resume_for_application(session):
    job_repo = JobRepository(session)
    app_repo = ApplicationRepository(session)
    resume_repo = ResumeRepository(session)
    ar_repo = ApplicationResumeRepository(session)

    job = await job_repo.create(make_job())
    app = await app_repo.create(make_application(job_id=job.id))
    resume = await resume_repo.create(make_resume())

    await ar_repo.create(ApplicationResume(application_id=app.id, resume_id=resume.id))
    fetched_resume = await ar_repo.get_resume_for_application(app.id)
    assert fetched_resume is not None
    assert fetched_resume.id == resume.id


@pytest.mark.asyncio
async def test_get_for_application_none(session):
    repo = ApplicationResumeRepository(session)
    result = await repo.get_for_application(uuid.uuid4())
    assert result is None


# ===========================================================================
# NotificationRepository tests
# ===========================================================================


@pytest.mark.asyncio
async def test_notification_create_and_get(session):
    job_repo = JobRepository(session)
    notif_repo = NotificationRepository(session)
    job = await job_repo.create(make_job())
    notif = await notif_repo.create(make_notification(job_id=job.id))
    fetched = await notif_repo.get_by_id(notif.id)
    assert fetched.notification_type == NotificationType.new_job_found


@pytest.mark.asyncio
async def test_list_pending(session):
    notif_repo = NotificationRepository(session)
    await notif_repo.create(
        make_notification(delivery_status=NotificationDeliveryStatus.pending)
    )
    await notif_repo.create(
        make_notification(delivery_status=NotificationDeliveryStatus.sent)
    )
    pending = await notif_repo.list_pending()
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_count_pending(session):
    notif_repo = NotificationRepository(session)
    await notif_repo.create(
        make_notification(delivery_status=NotificationDeliveryStatus.pending)
    )
    await notif_repo.create(
        make_notification(delivery_status=NotificationDeliveryStatus.pending)
    )
    assert await notif_repo.count_pending() == 2


@pytest.mark.asyncio
async def test_notification_list_by_job(session):
    job_repo = JobRepository(session)
    notif_repo = NotificationRepository(session)
    job = await job_repo.create(make_job())
    await notif_repo.create(make_notification(job_id=job.id))
    await notif_repo.create(make_notification(job_id=job.id))
    await notif_repo.create(make_notification())  # no job_id
    results = await notif_repo.list_by_job(job.id)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_list_older_than_notifications(session):
    notif_repo = NotificationRepository(session)
    await notif_repo.create(make_notification())
    cutoff = datetime(2099, 1, 1, tzinfo=timezone.utc)
    results = await notif_repo.list_older_than(cutoff)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_notification_paginated_by_status(session):
    notif_repo = NotificationRepository(session)
    for _ in range(5):
        await notif_repo.create(
            make_notification(delivery_status=NotificationDeliveryStatus.pending)
        )
    page = Pagination(page=1, page_size=3)
    result = await notif_repo.list_paginated_by_status(
        NotificationDeliveryStatus.pending, page
    )
    assert result.total == 5
    assert len(result.items) == 3


# ===========================================================================
# PortalConfigRepository tests
# ===========================================================================


@pytest.mark.asyncio
async def test_portal_config_create_and_get_by_name(session):
    repo = PortalConfigRepository(session)
    await repo.create(make_portal_config(portal_name="linkedin"))
    result = await repo.get_by_name("linkedin")
    assert result.portal_name == "linkedin"


@pytest.mark.asyncio
async def test_portal_config_get_by_name_not_found(session):
    repo = PortalConfigRepository(session)
    with pytest.raises(EntityNotFound):
        await repo.get_by_name("unknown-portal")


@pytest.mark.asyncio
async def test_portal_config_get_by_name_or_none(session):
    repo = PortalConfigRepository(session)
    result = await repo.get_by_name_or_none("nobody")
    assert result is None


@pytest.mark.asyncio
async def test_list_enabled(session):
    repo = PortalConfigRepository(session)
    await repo.create(make_portal_config(portal_name="linkedin", is_enabled=True))
    await repo.create(make_portal_config(portal_name="indeed", is_enabled=False))
    enabled = await repo.list_enabled()
    assert len(enabled) == 1
    assert enabled[0].portal_name == "linkedin"


@pytest.mark.asyncio
async def test_list_all_portals(session):
    repo = PortalConfigRepository(session)
    await repo.create(make_portal_config(portal_name="linkedin"))
    await repo.create(make_portal_config(portal_name="greenhouse"))
    all_portals = await repo.list_all_portals()
    assert len(all_portals) == 2


@pytest.mark.asyncio
async def test_exists_by_name(session):
    repo = PortalConfigRepository(session)
    await repo.create(make_portal_config(portal_name="lever"))
    assert await repo.exists_by_name("lever") is True
    assert await repo.exists_by_name("absent") is False


@pytest.mark.asyncio
async def test_count_enabled(session):
    repo = PortalConfigRepository(session)
    await repo.create(make_portal_config(portal_name="a", is_enabled=True))
    await repo.create(make_portal_config(portal_name="b", is_enabled=True))
    await repo.create(make_portal_config(portal_name="c", is_enabled=False))
    assert await repo.count_enabled() == 2


# ===========================================================================
# TaskLogRepository tests
# ===========================================================================


@pytest.mark.asyncio
async def test_task_log_create_and_get(session):
    repo = TaskLogRepository(session)
    task = await repo.create(make_task_log())
    fetched = await repo.get_by_id(task.id)
    assert fetched.task_type == TaskType.job_enrichment


@pytest.mark.asyncio
async def test_get_by_cloud_task_name(session):
    repo = TaskLogRepository(session)
    name = f"projects/p/queues/q/tasks/{uuid.uuid4()}"
    task = await repo.create(make_task_log(cloud_task_name=name))
    result = await repo.get_by_cloud_task_name(name)
    assert result is not None
    assert result.id == task.id


@pytest.mark.asyncio
async def test_get_by_cloud_task_name_none(session):
    repo = TaskLogRepository(session)
    result = await repo.get_by_cloud_task_name("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_exists_by_cloud_task_name(session):
    repo = TaskLogRepository(session)
    name = f"tasks/{uuid.uuid4()}"
    await repo.create(make_task_log(cloud_task_name=name))
    assert await repo.exists_by_cloud_task_name(name) is True
    assert await repo.exists_by_cloud_task_name("no") is False


@pytest.mark.asyncio
async def test_list_by_entity(session):
    repo = TaskLogRepository(session)
    entity = str(uuid.uuid4())
    await repo.create(
        make_task_log(entity_id=entity, task_type=TaskType.job_enrichment)
    )
    await repo.create(make_task_log(entity_id=entity, task_type=TaskType.notification))
    results = await repo.list_by_entity(entity)
    assert len(results) == 2


@pytest.mark.asyncio
async def test_list_by_entity_filtered_by_type(session):
    repo = TaskLogRepository(session)
    entity = str(uuid.uuid4())
    await repo.create(
        make_task_log(entity_id=entity, task_type=TaskType.job_enrichment)
    )
    await repo.create(make_task_log(entity_id=entity, task_type=TaskType.notification))
    results = await repo.list_by_entity(entity, TaskType.job_enrichment)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_list_by_status_task_log(session):
    repo = TaskLogRepository(session)
    await repo.create(make_task_log(status=TaskStatus.pending))
    await repo.create(make_task_log(status=TaskStatus.success))
    pending = await repo.list_by_status(TaskStatus.pending)
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_list_older_than_task_log(session):
    repo = TaskLogRepository(session)
    await repo.create(make_task_log())
    cutoff = datetime(2099, 1, 1, tzinfo=timezone.utc)
    results = await repo.list_older_than(cutoff)
    assert len(results) >= 1


@pytest.mark.asyncio
async def test_count_by_status_task_log(session):
    repo = TaskLogRepository(session)
    await repo.create(make_task_log(status=TaskStatus.failed))
    await repo.create(make_task_log(status=TaskStatus.failed))
    await repo.create(make_task_log(status=TaskStatus.success))
    assert await repo.count_by_status(TaskStatus.failed) == 2


@pytest.mark.asyncio
async def test_count_by_entity(session):
    repo = TaskLogRepository(session)
    entity = str(uuid.uuid4())
    await repo.create(make_task_log(entity_id=entity))
    await repo.create(make_task_log(entity_id=entity))
    assert await repo.count_by_entity(entity) == 2


# ===========================================================================
# Transaction / rollback tests
# ===========================================================================


@pytest.mark.asyncio
async def test_rollback_on_integrity_error(session):
    """
    Creating two raw messages with the same (telegram_message_id, channel_id)
    violates the unique constraint — BaseRepository.create() should raise
    RepositoryError after rolling back the session.
    """
    repo = JobRawMessageRepository(session)
    await repo.create(make_raw_message(telegram_message_id=42, channel_id=-100))
    with pytest.raises(RepositoryError):
        await repo.create(make_raw_message(telegram_message_id=42, channel_id=-100))


@pytest.mark.asyncio
async def test_session_not_committed_by_repo(session):
    """
    Repositories flush but do not commit. After flush the entity is visible
    within the same session but a rollback removes it.
    """
    repo = JobRawMessageRepository(session)
    msg = await repo.create(make_raw_message(telegram_message_id=999))
    # Visible in the same session
    assert await repo.get_by_id_or_none(msg.id) is not None
    # Rollback removes it (performed by the session fixture teardown)
    await session.rollback()
    assert await repo.get_by_id_or_none(msg.id) is None
