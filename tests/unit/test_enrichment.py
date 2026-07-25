import uuid
from typing import Type

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.ai.client import AIRetryableError, AIValidationError, GeminiClient
from src.core.enums import JobStatus
from src.jobs.dto import AIEnrichmentResponse
from src.jobs.models import Job, JobRawMessage
from src.jobs.repository import JobRepository
from src.jobs.services.enricher import JobEnrichmentService


class MockGeminiClient(GeminiClient):
    def __init__(self, response_to_return=None, exception_to_raise=None):
        super().__init__()
        self.response_to_return = response_to_return
        self.exception_to_raise = exception_to_raise

    async def generate_structured(
        self, prompt: str, schema: Type
    ) -> AIEnrichmentResponse:
        if self.exception_to_raise:
            raise self.exception_to_raise
        return self.response_to_return


@pytest.mark.asyncio
async def test_enrich_job_success(session: AsyncSession):
    # Setup Data
    job_id = uuid.uuid4()
    raw_message = JobRawMessage(
        telegram_message_id=123, channel_id=456, raw_text="Awesome Job description here"
    )
    session.add(raw_message)
    await session.commit()
    await session.refresh(raw_message)

    job = Job(id=job_id, raw_message_id=raw_message.id, status=JobStatus.pending)
    session.add(job)
    await session.commit()

    JobRepository(session)

    mock_response = AIEnrichmentResponse(
        company_name="Acme Corp",
        role_title="Senior Python Developer",
        location="New York",
        is_remote=True,
        relevance_score=95.5,
        reasoning="Matches perfectly",
        confidence=0.9,
    )

    ai_client = MockGeminiClient(response_to_return=mock_response)
    service = JobEnrichmentService(session, ai_client)

    # Act
    result = await service.enrich_job(job_id)

    # Assert
    assert result is True
    await session.refresh(job)
    assert job.status == JobStatus.enriched
    assert job.company_name == "Acme Corp"
    assert job.role_title == "Senior Python Developer"
    assert job.relevance_score == 95.5
    assert job.is_remote is True


@pytest.mark.asyncio
async def test_enrich_job_retryable_error(session: AsyncSession):
    # Setup Data
    job_id = uuid.uuid4()
    raw_message = JobRawMessage(
        telegram_message_id=124, channel_id=456, raw_text="Another description"
    )
    session.add(raw_message)
    await session.commit()
    await session.refresh(raw_message)

    job = Job(id=job_id, raw_message_id=raw_message.id, status=JobStatus.pending)
    session.add(job)
    await session.commit()

    JobRepository(session)
    ai_client = MockGeminiClient(exception_to_raise=AIRetryableError("Timeout"))
    service = JobEnrichmentService(session, ai_client)

    # Act
    result = await service.enrich_job(job_id)

    # Assert
    assert result is False
    await session.refresh(job)
    assert job.status == JobStatus.pending


@pytest.mark.asyncio
async def test_enrich_job_validation_error(session: AsyncSession):
    # Setup Data
    job_id = uuid.uuid4()
    raw_message = JobRawMessage(
        telegram_message_id=125, channel_id=456, raw_text="Bad description"
    )
    session.add(raw_message)
    await session.commit()
    await session.refresh(raw_message)

    job = Job(id=job_id, raw_message_id=raw_message.id, status=JobStatus.pending)
    session.add(job)
    await session.commit()

    JobRepository(session)
    ai_client = MockGeminiClient(exception_to_raise=AIValidationError("Malformed JSON"))
    service = JobEnrichmentService(session, ai_client)

    # Act
    result = await service.enrich_job(job_id)

    # Assert
    assert result is False
    await session.refresh(job)
    # Since we are returning False to retry validation errors, status should remain pending
    assert job.status == JobStatus.pending


@pytest.mark.asyncio
async def test_enrich_job_not_found(session: AsyncSession):
    JobRepository(session)
    ai_client = MockGeminiClient()
    service = JobEnrichmentService(session, ai_client)

    result = await service.enrich_job(uuid.uuid4())
    assert result is None


import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

import src.core.model_registry  # noqa: F401
from src.core.database import Base

TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture(scope="function")
async def engine():
    import sqlalchemy as sa
    from sqlalchemy.dialects.postgresql import JSONB

    eng = create_async_engine(TEST_DATABASE_URL, echo=False)

    @event.listens_for(eng.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    jsonb_columns = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                jsonb_columns.append(column)
                column.type = sa.JSON()

    try:
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    finally:
        for column in jsonb_columns:
            column.type = JSONB()

    yield eng

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await eng.dispose()


@pytest_asyncio.fixture(scope="function")
async def session(engine):
    async_session_maker = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    async with async_session_maker() as sess:
        yield sess
        await sess.rollback()
