"""
FastAPI lifespan manager.

Enhanced in the final integration phase to include:
  - Startup validation (settings + DB probe)
  - Graceful shutdown of engine and any background resources
  - Structured startup/shutdown log messages
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.core.database import engine
from src.core.startup import StartupError, StartupValidator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan manager.

    Startup:
      1. Run StartupValidator (settings check + DB probe).
         If validation fails, logs the error and re-raises — the process
         exits non-zero so the orchestrator (Cloud Run / Kubernetes) knows
         the pod is unhealthy.

    Shutdown:
      1. Dispose the SQLAlchemy async engine (returns all connections to pool).
    """
    # ── Startup ────────────────────────────────────────────────────────
    logger.info("career-agent starting up…")

    # Allow startup validation to be skipped in test environments
    skip_startup = os.getenv("SKIP_STARTUP_VALIDATION", "false").lower() in (
        "true",
        "1",
        "yes",
    )

    if not skip_startup:
        validator = StartupValidator(skip_db_probe=False)
        try:
            await validator.validate()
        except StartupError as exc:
            logger.critical("Startup validation FAILED: %s", exc)
            raise  # abort startup; process exits non-zero

    logger.info("career-agent ready to serve.")

    yield  # Application serves requests during this yield

    # ── Shutdown ───────────────────────────────────────────────────────
    logger.info("career-agent shutting down…")
    await engine.dispose()
    logger.info("Database engine disposed. Shutdown complete.")
