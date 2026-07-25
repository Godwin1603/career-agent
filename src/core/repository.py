"""
Generic async repository base class.

All domain repositories inherit from BaseRepository[ModelT].
It provides type-safe CRUD, pagination, filtering, and ordering helpers
backed by SQLAlchemy 2.x AsyncSession.

Design rules:
  - Repositories receive a session; they never create or commit sessions.
  - No business logic lives here.
  - Every public method is async.
  - SQLAlchemy 2.x select() API is used throughout (no legacy Query API).
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Generic, Sequence, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from src.core.exceptions import EntityNotFound, RepositoryError

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class Pagination:
    """Encapsulates pagination parameters validated at construction."""

    def __init__(self, *, page: int = 1, page_size: int = 20) -> None:
        if page < 1:
            raise ValueError("page must be >= 1")
        if not (1 <= page_size <= 500):
            raise ValueError("page_size must be between 1 and 500")
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class PaginatedResult(Generic[ModelT]):
    """Typed container for a paginated query result."""

    def __init__(
        self,
        items: Sequence[ModelT],
        total: int,
        pagination: Pagination,
    ) -> None:
        self.items = list(items)
        self.total = total
        self.pagination = pagination

    @property
    def pages(self) -> int:
        if self.pagination.page_size == 0:
            return 0

        return math.ceil(self.total / self.pagination.page_size)

    @property
    def has_next(self) -> bool:
        return self.pagination.page < self.pages

    @property
    def has_prev(self) -> bool:
        return self.pagination.page > 1


class BaseRepository(Generic[ModelT]):
    """
    Generic async repository for a single SQLAlchemy mapped model.

    Usage:
        class JobRepository(BaseRepository[Job]):
            model = Job

    The subclass declares only the model class attribute. All generic
    CRUD operations are provided by this base class. Domain-specific
    query methods are added directly to the subclass.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create(self, instance: ModelT) -> ModelT:
        """
        Persist a new model instance.

        The caller is responsible for constructing the instance and for
        committing or rolling back the session.
        """
        try:
            self._session.add(instance)
            await self._session.flush()
            return instance
        except IntegrityError as exc:
            raise RepositoryError(
                f"Integrity error creating {self.model.__name__}: {exc.orig}"
            ) from exc
        except SQLAlchemyError as exc:
            raise RepositoryError(
                f"Database error creating {self.model.__name__}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Read — by primary key
    # ------------------------------------------------------------------

    async def get_by_id(self, entity_id: uuid.UUID) -> ModelT:
        """
        Return the entity with the given primary key.
        Raises EntityNotFound if no row exists.
        """
        result = await self._session.get(self.model, entity_id)
        if result is None:
            raise EntityNotFound(self.model.__name__, entity_id)
        return result

    async def get_by_id_or_none(self, entity_id: uuid.UUID) -> ModelT | None:
        """Return the entity with the given primary key, or None if absent."""
        return await self._session.get(self.model, entity_id)

    # ------------------------------------------------------------------
    # Read — single row by filter
    # ------------------------------------------------------------------

    async def get_one(self, *where_clauses: Any) -> ModelT:
        """
        Return the first row matching all where_clauses.
        Raises EntityNotFound if no row matches.
        """
        stmt = select(self.model).where(*where_clauses)
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        if row is None:
            raise EntityNotFound(self.model.__name__, where_clauses)
        return row

    async def get_one_or_none(self, *where_clauses: Any) -> ModelT | None:
        """Return the first row matching all where_clauses, or None."""
        stmt = select(self.model).where(*where_clauses)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    # ------------------------------------------------------------------
    # Read — multiple rows
    # ------------------------------------------------------------------

    async def list_all(
        self,
        *where_clauses: Any,
        order_by: Any = None,
    ) -> list[ModelT]:
        """
        Return all rows matching where_clauses.
        Pass order_by as a SQLAlchemy column expression to sort results.
        """
        stmt = select(self.model)
        if where_clauses:
            stmt = stmt.where(*where_clauses)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_paginated(
        self,
        pagination: Pagination,
        *where_clauses: Any,
        order_by: Any = None,
    ) -> PaginatedResult[ModelT]:
        """
        Return a paginated result for the given where_clauses.

        Executes two queries: one for the total count and one for the page.
        """
        count_stmt = select(func.count()).select_from(self.model)
        if where_clauses:
            count_stmt = count_stmt.where(*where_clauses)
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        stmt = select(self.model)
        if where_clauses:
            stmt = stmt.where(*where_clauses)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        stmt = stmt.offset(pagination.offset).limit(pagination.limit)
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())

        return PaginatedResult(items=items, total=total, pagination=pagination)

    # ------------------------------------------------------------------
    # Exists / Count
    # ------------------------------------------------------------------

    async def exists(self, *where_clauses: Any) -> bool:
        """
        Return True if at least one row matches where_clauses.
        Uses a short-circuiting existence query for performance.
        """
        stmt = select(1).select_from(self.model)
        if where_clauses:
            stmt = stmt.where(*where_clauses)
        stmt = stmt.limit(1)
        result = await self._session.execute(stmt)
        return result.first() is not None

    async def count(self, *where_clauses: Any) -> int:
        """Return the number of rows matching where_clauses."""
        stmt = select(func.count()).select_from(self.model)
        if where_clauses:
            stmt = stmt.where(*where_clauses)
        result = await self._session.execute(stmt)
        return result.scalar_one() or 0

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update(self, instance: ModelT, **values: Any) -> ModelT:
        """
        Apply field updates to an already-loaded model instance and flush.

        Callers pass keyword arguments matching model attribute names.
        The session is flushed but not committed.
        """
        for field, value in values.items():
            setattr(instance, field, value)
        try:
            await self._session.flush()
            return instance
        except IntegrityError as exc:
            raise RepositoryError(
                f"Integrity error updating {self.model.__name__}: {exc.orig}"
            ) from exc
        except SQLAlchemyError as exc:
            raise RepositoryError(
                f"Database error updating {self.model.__name__}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, instance: ModelT) -> None:
        """
        Delete a loaded model instance and flush.
        The session is not committed — the caller owns the transaction.
        """
        try:
            await self._session.delete(instance)
            await self._session.flush()
        except SQLAlchemyError as exc:
            raise RepositoryError(
                f"Database error deleting {self.model.__name__}: {exc}"
            ) from exc

    async def delete_by_id(self, entity_id: uuid.UUID) -> None:
        """
        Delete an entity by primary key using a direct DELETE statement.
        Raises EntityNotFound if no matching row was affected.
        """
        stmt = delete(self.model).where(self.model.id == entity_id)
        try:
            result = await self._session.execute(stmt)
            await self._session.flush()
            if result.rowcount == 0:
                raise EntityNotFound(self.model.__name__, entity_id)
        except EntityNotFound:
            raise
        except SQLAlchemyError as exc:
            raise RepositoryError(
                f"Database error deleting {self.model.__name__}: {exc}"
            ) from exc
