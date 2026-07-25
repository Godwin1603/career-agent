"""
Repository for the applications domain.

Provides persistence operations for Application and ApplicationEvent.
No business logic. Session is injected by the caller.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from src.applications.models import Application, ApplicationEvent
from src.core.enums import ApplicationStatus, ApplicationStrategy
from src.core.exceptions import EntityNotFound
from src.core.repository import BaseRepository, PaginatedResult, Pagination


class ApplicationRepository(BaseRepository[Application]):
    """Persistence operations for application attempt records."""

    model = Application

    async def get_by_id_with_events(self, application_id: uuid.UUID) -> Application:
        """
        Load an Application with its events collection eagerly loaded.
        Raises EntityNotFound if not found.

        Used by workers and the stale detector that inspect the full event history.
        """
        stmt = (
            select(Application)
            .where(Application.id == application_id)
            .options(selectinload(Application.events))
        )
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        if row is None:
            raise EntityNotFound(Application.__name__, application_id)
        return row

    async def get_by_job_and_strategy(
        self,
        job_id: uuid.UUID,
        strategy: ApplicationStrategy,
    ) -> Application | None:
        """
        Return the application record for a specific (job, strategy) pair, or None.
        Reflects the unique constraint uq_applications_job_strategy.
        """
        stmt = select(Application).where(
            and_(
                Application.job_id == job_id,
                Application.strategy == strategy,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def exists_for_job_and_strategy(
        self,
        job_id: uuid.UUID,
        strategy: ApplicationStrategy,
    ) -> bool:
        """
        Return True if an application already exists for this (job, strategy) pair.
        Used to prevent duplicate application dispatch.
        """
        return await self.exists(
            Application.job_id == job_id,
            Application.strategy == strategy,
        )

    async def list_by_job(self, job_id: uuid.UUID) -> list[Application]:
        """
        Return all applications for a given job, ordered by strategy for consistency.
        """
        stmt = (
            select(Application)
            .where(Application.job_id == job_id)
            .order_by(Application.strategy.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_status(
        self,
        status: ApplicationStatus,
        *,
        limit: int = 100,
    ) -> list[Application]:
        """
        Return up to `limit` applications in the given status, oldest-first.
        """
        stmt = (
            select(Application)
            .where(Application.status == status)
            .order_by(Application.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_stale_in_progress(
        self,
        stale_cutoff: datetime,
        *,
        limit: int = 100,
    ) -> list[Application]:
        """
        Return applications that are in-progress and whose updated_at is older
        than `stale_cutoff`. Used by the dead-letter stale detector to find
        applications whose Cloud Tasks have exhausted all retry attempts.
        """
        stmt = (
            select(Application)
            .where(
                and_(
                    Application.status == ApplicationStatus.in_progress,
                    Application.updated_at < stale_cutoff,
                )
            )
            .order_by(Application.updated_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_strategy(
        self,
        strategy: ApplicationStrategy,
        *,
        limit: int = 100,
    ) -> list[Application]:
        """Return up to `limit` applications for the given strategy, newest-first."""
        stmt = (
            select(Application)
            .where(Application.strategy == strategy)
            .order_by(Application.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_paginated_by_status(
        self,
        status: ApplicationStatus,
        pagination: Pagination,
    ) -> PaginatedResult[Application]:
        """Return a paginated list of applications in the given status."""
        return await self.list_paginated(
            pagination,
            Application.status == status,
            order_by=Application.updated_at.desc(),
        )

    async def count_by_status(self, status: ApplicationStatus) -> int:
        """Return the total number of applications in the given status."""
        return await self.count(Application.status == status)

    async def count_successful_today(self, since: datetime) -> int:
        """
        Return the number of successful applications created on or after `since`.
        Used for rate-limiting checks in the dispatcher.
        """
        return await self.count(
            Application.status == ApplicationStatus.success,
            Application.applied_at >= since,
        )


class ApplicationEventRepository(BaseRepository[ApplicationEvent]):
    """Persistence operations for the application event audit log."""

    model = ApplicationEvent

    async def list_by_application(
        self,
        application_id: uuid.UUID,
    ) -> list[ApplicationEvent]:
        """
        Return all events for the given application, ordered oldest-first.
        The event log is append-only; ordering by created_at is the natural order.
        """
        stmt = (
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == application_id)
            .order_by(ApplicationEvent.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_event_type(
        self,
        application_id: uuid.UUID,
        event_type: str,
    ) -> list[ApplicationEvent]:
        """
        Return events of a specific type for the given application.
        Useful for checking whether a specific transition has already occurred.
        """
        stmt = (
            select(ApplicationEvent)
            .where(
                and_(
                    ApplicationEvent.application_id == application_id,
                    ApplicationEvent.event_type == event_type,
                )
            )
            .order_by(ApplicationEvent.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_application(self, application_id: uuid.UUID) -> int:
        """Return the total number of events for a given application."""
        return await self.count(ApplicationEvent.application_id == application_id)
