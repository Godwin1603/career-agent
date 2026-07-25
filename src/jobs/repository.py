"""
Repository for the jobs domain.

Provides persistence operations for Job and JobRawMessage.
No business logic. Session is injected by the caller.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select

from src.core.enums import JobStatus, RawMessageStatus
from src.core.exceptions import EntityNotFound
from src.core.repository import BaseRepository, PaginatedResult, Pagination
from src.jobs.models import Job, JobRawMessage


class JobRawMessageRepository(BaseRepository[JobRawMessage]):
    """Persistence operations for raw Telegram message records."""

    model = JobRawMessage

    async def get_by_telegram_ids(
        self, telegram_message_id: int, channel_id: int
    ) -> JobRawMessage | None:
        """
        Return the raw message matching the given Telegram message and channel IDs.
        Returns None if no matching record exists (used for deduplication checks).
        """
        stmt = select(JobRawMessage).where(
            and_(
                JobRawMessage.telegram_message_id == telegram_message_id,
                JobRawMessage.channel_id == channel_id,
            )
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def exists_by_telegram_ids(
        self, telegram_message_id: int, channel_id: int
    ) -> bool:
        """
        Return True if a raw message with these Telegram IDs already exists.
        Used as a fast deduplication check before insert.
        """
        return await self.exists(
            JobRawMessage.telegram_message_id == telegram_message_id,
            JobRawMessage.channel_id == channel_id,
        )

    async def list_by_status(
        self,
        status: RawMessageStatus,
        *,
        limit: int = 100,
    ) -> list[JobRawMessage]:
        """
        Return up to `limit` raw messages in the given status, ordered oldest-first.
        Used by the enrichment worker to pick up pending messages.
        """
        stmt = (
            select(JobRawMessage)
            .where(JobRawMessage.status == status)
            .order_by(JobRawMessage.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_older_than(self, cutoff: datetime) -> list[JobRawMessage]:
        """
        Return all raw messages with created_at before `cutoff`.
        Used by the cleanup scheduler for 30-day retention enforcement.
        """
        stmt = (
            select(JobRawMessage)
            .where(JobRawMessage.created_at < cutoff)
            .order_by(JobRawMessage.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class JobRepository(BaseRepository[Job]):
    """Persistence operations for enriched job postings."""

    model = Job

    async def get_by_id_with_applications(self, job_id: uuid.UUID) -> Job:
        """
        Load a Job and eagerly join its applications collection.
        Raises EntityNotFound if not found.

        Used by workers that need to inspect all strategies for a job before
        dispatching new tasks.
        """
        from sqlalchemy.orm import selectinload

        stmt = (
            select(Job).where(Job.id == job_id).options(selectinload(Job.applications))
        )
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        if row is None:
            raise EntityNotFound(Job.__name__, job_id)
        return row

    async def get_by_status(
        self,
        status: JobStatus,
        *,
        limit: int = 100,
    ) -> list[Job]:
        """
        Return up to `limit` jobs in the given status, ordered by created_at asc.
        """
        stmt = (
            select(Job)
            .where(Job.status == status)
            .order_by(Job.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self, *, limit: int = 100) -> list[Job]:
        """
        Return up to `limit` enriched jobs that have not expired and are not
        skipped. "Active" means status=enriched and either no expires_at or
        expires_at in the future.
        """
        from sqlalchemy import or_
        from sqlalchemy.sql import func

        stmt = (
            select(Job)
            .where(
                and_(
                    Job.status == JobStatus.enriched,
                    or_(
                        Job.expires_at.is_(None),
                        Job.expires_at > func.now(),
                    ),
                )
            )
            .order_by(Job.relevance_score.desc().nulls_last(), Job.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_expired(self, cutoff: datetime) -> list[Job]:
        """
        Return all jobs that have an expires_at before `cutoff` and are not
        already marked expired. Used by the cleanup scheduler.
        """
        stmt = (
            select(Job)
            .where(
                and_(
                    Job.expires_at < cutoff,
                    Job.status != JobStatus.expired,
                )
            )
            .order_by(Job.expires_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_portal(
        self,
        portal_name: str,
        *,
        limit: int = 100,
    ) -> list[Job]:
        """
        Return up to `limit` jobs whose detected_portal matches the given name.
        """
        stmt = (
            select(Job)
            .where(Job.detected_portal == portal_name)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_above_relevance(
        self,
        min_score: float,
        *,
        limit: int = 100,
    ) -> list[Job]:
        """
        Return up to `limit` jobs with relevance_score >= min_score, highest first.
        Used by the application dispatcher threshold check.
        """
        stmt = (
            select(Job)
            .where(
                and_(
                    Job.relevance_score.isnot(None),
                    Job.relevance_score >= min_score,
                )
            )
            .order_by(Job.relevance_score.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_paginated_by_status(
        self,
        status: JobStatus,
        pagination: Pagination,
        order_by: Any = None,
    ) -> PaginatedResult[Job]:
        """
        Return a paginated list of jobs in the given status.
        Defaults to created_at desc if no order_by provided.
        """
        effective_order = order_by if order_by is not None else Job.created_at.desc()
        return await self.list_paginated(
            pagination,
            Job.status == status,
            order_by=effective_order,
        )

    async def count_by_status(self, status: JobStatus) -> int:
        """Return the total number of jobs in the given status."""
        return await self.count(Job.status == status)
