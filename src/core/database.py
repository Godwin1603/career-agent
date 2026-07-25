from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings

# Setup the async SQLAlchemy engine using asyncpg
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True for SQL query logging during debugging
    pool_pre_ping=True,  # Verify connection health before usage
    pool_size=5,  # Moderate pool size for Cloud Run
    max_overflow=10,
)

# Setup the async session maker
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

# Base class for all SQLAlchemy declarative models (SQLAlchemy 2.x style)
class Base(DeclarativeBase):
    pass


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for injecting an async database session into endpoints.
    The async context manager handles session cleanup on exit.
    """
    async with async_session_maker() as session:
        yield session
