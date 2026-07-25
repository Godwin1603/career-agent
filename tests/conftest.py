# Shared pytest fixtures for the career-agent test suite.
# pytest-asyncio is configured in pyproject.toml (asyncio_mode = "auto").
# The event loop is managed automatically — no custom event_loop fixture is needed.

import subprocess

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from src.core.config import settings


@pytest.fixture(scope="session")
async def db_engine():
    """
    Runs 'alembic upgrade head' against the configured DATABASE_URL and yields
    an async engine pointed at the upgraded database.

    Skipped automatically if the database is unreachable (e.g. in offline CI).
    """
    try:
        engine = create_async_engine(settings.DATABASE_URL)
        # Verify connectivity before running migrations
        async with engine.connect():
            pass
    except Exception:
        pytest.skip("Database not reachable — skipping Alembic integration tests")
        return

    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade head failed:\n{result.stderr}")

    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def db_engine_after_downgrade(db_engine):
    """
    Runs 'alembic downgrade base' against the already-upgraded database and
    yields an async engine for asserting the tables were removed.
    """
    result = subprocess.run(
        ["alembic", "downgrade", "base"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic downgrade base failed:\n{result.stderr}")

    yield db_engine
