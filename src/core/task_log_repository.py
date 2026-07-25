"""
Repository for the task_log domain.

Provides persistence operations for TaskLog records.
No business logic. Session is injected by the caller.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, select

from src.core.enums import TaskStatus, TaskType
from src.core.repository import BaseRepository
from src.core.task_log import TaskLog


class TaskLogRepository(BaseRepository[TaskLog]):
    """Persistence operations for Cloud Task audit log entries."""

    model = TaskLog

    async def get_by_cloud_task_name(self, cloud_task_name: str) -> TaskLog | None:
        """
        Return the task log entry matching the given Cloud Tasks task name, or None.
        Used for idempotency checks: if a task name already exists in the log,
        the task has already been processed (or is in progress).
        """
        stmt = select(TaskLog).where(TaskLog.cloud_task_name == cloud_task_name)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def exists_by_cloud_task_name(self, cloud_task_name: str) -> bool:
        """
        Return True if a task log entry already exists for this Cloud Tasks name.
        Fast idempotency pre-check before doing any expensive work.
        """
        return await self.exists(TaskLog.cloud_task_name == cloud_task_name)

    async def list_by_entity(
        self,
        entity_id: str,
        task_type: TaskType | None = None,
        *,
        limit: int = 100,
    ) -> list[TaskLog]:
        """
        Return up to `limit` task log entries for the given entity ID.
        Optionally filter by task_type. Ordered newest-first.

        `entity_id` is stored as a string (UUID) matching the column definition.
        """
        conditions = [TaskLog.entity_id == entity_id]
        if task_type is not None:
            conditions.append(TaskLog.task_type == task_type)
        stmt = (
            select(TaskLog)
            .where(and_(*conditions))
            .order_by(TaskLog.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_status(
        self,
        status: TaskStatus,
        *,
        limit: int = 100,
    ) -> list[TaskLog]:
        """Return up to `limit` task log entries in the given status, oldest-first."""
        stmt = (
            select(TaskLog)
            .where(TaskLog.status == status)
            .order_by(TaskLog.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_older_than(self, cutoff: datetime) -> list[TaskLog]:
        """
        Return all task log entries with created_at before `cutoff`.
        Used by the cleanup scheduler for 60-day retention enforcement.
        """
        stmt = (
            select(TaskLog)
            .where(TaskLog.created_at < cutoff)
            .order_by(TaskLog.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_failed(self, *, limit: int = 100) -> list[TaskLog]:
        """Return up to `limit` failed task log entries, oldest-first."""
        return await self.list_by_status(TaskStatus.failed, limit=limit)

    async def count_by_status(self, status: TaskStatus) -> int:
        """Return the total count of task log entries in the given status."""
        return await self.count(TaskLog.status == status)

    async def count_by_entity(self, entity_id: str) -> int:
        """Return the total number of task attempts recorded for the given entity."""
        return await self.count(TaskLog.entity_id == entity_id)
