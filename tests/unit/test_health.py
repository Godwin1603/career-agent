import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.mark.asyncio
async def test_liveness_probe():
    """
    Verifies the liveness probe returns 200 OK.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_readiness_probe_fails_without_db():
    """
    Verifies the readiness probe returns 503 when the DB is unavailable.
    During unit tests, there is no DB running unless mocked, so it should fail.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unready", "database": "disconnected"}
