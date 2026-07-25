import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.core.database import engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan manager. Handles startup and shutdown events cleanly.
    """
    logger.info("Starting up career-agent FastAPI application...")

    # Connect to dependencies (e.g. Redis, Telethon listener) here in future phases.

    yield  # Application runs during this yield

    logger.info("Shutting down career-agent FastAPI application...")

    # Disconnect dependencies cleanly
    await engine.dispose()
    logger.info("Database engine disposed.")
