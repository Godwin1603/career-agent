import logging

from fastapi import Depends, FastAPI, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db_session
from src.core.lifespan import lifespan
from src.core.logging import setup_logging

# Initialize logging for the application
setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Career Agent API",
    description="AI-powered personal career automation platform",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health/live", tags=["Health"])
async def liveness_probe():
    """
    Liveness probe for orchestration (e.g. Kubernetes/Cloud Run).
    Returns 200 OK if the FastAPI server is running.
    """
    return {"status": "alive"}


@app.get("/health/ready", tags=["Health"])
async def readiness_probe(db: AsyncSession = Depends(get_db_session)):
    """
    Readiness probe for orchestration.
    Returns 200 OK if the server is ready to accept traffic (including DB connectivity).
    Returns 503 Service Unavailable if dependencies are not healthy.
    """
    try:
        # Simple query to verify database connectivity
        await db.execute(text("SELECT 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as e:
        logger.error(f"Readiness probe failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unready", "database": "disconnected"},
        )
