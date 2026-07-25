import pytest

import src.core.model_registry  # noqa: F401
from src.core.enums import RawMessageStatus
from src.jobs.services.ingestion import MessageIngestionService
from src.jobs.services.normalizer import JobNormalizer
from src.jobs.services.parser import JobParser


def test_parser_extracts_urls_and_salary():
    text = "Senior Backend Engineer - Acme Corp\nSalary: $120k - $150k\nApply here: https://boards.greenhouse.io/acme/123\nRemote"
    dto = JobParser.parse(text)

    assert dto.role_title == "Senior Backend Engineer"
    assert dto.company_name == "Acme Corp"
    assert dto.salary_range == "$120k - $150k"
    assert dto.application_url == "https://boards.greenhouse.io/acme/123"
    assert dto.is_remote is True
    assert dto.email_address is None


def test_normalizer_detects_portal():
    text = "Software Engineer | StartupInc\nApply here: https://jobs.lever.co/startupinc/abc"
    dto = JobParser.parse(text)
    normalized = JobNormalizer.normalize(dto)

    assert normalized.detected_portal == "lever"
    assert normalized.role_title == "Software Engineer"
    assert normalized.company_name == "StartupInc"


@pytest.mark.asyncio
async def test_ingestion_service(session):
    service = MessageIngestionService(session)
    text = "Data Scientist - Globex\nRemote\nhttps://workday.com/globex/123"

    # First ingest
    job = await service.ingest_message(1001, 2002, text)
    assert job is not None
    assert job.company_name == "Globex"
    assert job.role_title == "Data Scientist"
    assert job.detected_portal == "workday"

    # Verify raw message created
    raw_repo = service.raw_repo
    raw_msg = await raw_repo.get_by_telegram_ids(1001, 2002)
    assert raw_msg is not None
    assert raw_msg.status == RawMessageStatus.processed

    # Second ingest (duplicate)
    duplicate_job = await service.ingest_message(1001, 2002, text)
    assert duplicate_job is None


def test_parser_empty_message():
    dto = JobParser.parse("")
    assert dto.role_title is None
    assert dto.company_name is None
    assert dto.application_url is None


def test_parser_malformed_message():
    text = "Just some random text\nWith no URLs\nOr salaries"
    dto = JobParser.parse(text)
    assert dto.role_title == "Just some random text"
    assert dto.company_name == "With no URLs"
    assert dto.application_url is None


def test_parser_multiple_urls():
    text = "Role | Company\nApply: https://boards.greenhouse.io/acme/123\nForm: https://forms.gle/xyz"
    dto = JobParser.parse(text)
    assert dto.application_url == "https://boards.greenhouse.io/acme/123"
    assert dto.google_form_url == "https://forms.gle/xyz"


def test_parser_unicode_emojis():
    text = "🚀 Senior Rustacean - CrabCorp 🦀\nSalary: $150k - $200k\nhttps://jobs.lever.co/crab"
    dto = JobParser.parse(text)
    assert dto.role_title == "🚀 Senior Rustacean"
    assert dto.company_name == "CrabCorp 🦀"


@pytest.mark.asyncio
async def test_ingestion_service_repository_failure(session, monkeypatch):
    service = MessageIngestionService(session)
    text = "Data Scientist - Globex\nRemote\nhttps://workday.com/globex/123"

    # Mock create to raise an Exception
    async def mock_create(*args, **kwargs):
        raise Exception("DB Error")

    monkeypatch.setattr(service.job_repo, "create", mock_create)

    # Ingest should fail and return None
    job = await service.ingest_message(999, 888, text)
    assert job is None

    # Raw message should still exist but be FAILED
    raw_msg = await service.raw_repo.get_by_telegram_ids(999, 888)
    assert raw_msg is not None
    assert raw_msg.status == RawMessageStatus.failed


import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

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
