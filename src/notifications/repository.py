"""
Repository for the notifications domain.

Provides persistence operations for Notification records.
No business logic. Session is injected by the caller.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, select

from src.core.enums import NotificationDeliveryStatus, NotificationType
from src.core.repository import BaseRepository, PaginatedResult, Pagination
from src.notifications.models import Notification


class NotificationRepository(BaseRepository[Notification]):
    """Persistence operations for notification records."""

    model = Notification

    async def list_by_delivery_status(
        self,
        status: NotificationDeliveryStatus,
        *,
        limit: int = 100,
    ) -> list[Notification]:
        """
        Return up to `limit` notifications in the given delivery status,
        ordered oldest-first. Used by the notifier to find pending notifications.
        """
        stmt = (
            select(Notification)
            .where(Notification.delivery_status == status)
            .order_by(Notification.created_at.asc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending(self, *, limit: int = 100) -> list[Notification]:
        """
        Return up to `limit` undelivered notifications, oldest-first.
        Convenience wrapper around list_by_delivery_status(pending).
        """
        return await self.list_by_delivery_status(
            NotificationDeliveryStatus.pending, limit=limit
        )

    async def list_by_job(self, job_id: uuid.UUID) -> list[Notification]:
        """Return all notifications referencing the given job, newest-first."""
        stmt = (
            select(Notification)
            .where(Notification.job_id == job_id)
            .order_by(Notification.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_application(
        self, application_id: uuid.UUID
    ) -> list[Notification]:
        """Return all notifications referencing the given application, newest-first."""
        stmt = (
            select(Notification)
            .where(Notification.application_id == application_id)
            .order_by(Notification.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_type(
        self,
        notification_type: NotificationType,
        *,
        limit: int = 100,
    ) -> list[Notification]:
        """
        Return up to `limit` notifications of the given type, newest-first.
        Useful for auditing or debugging specific notification categories.
        """
        stmt = (
            select(Notification)
            .where(Notification.notification_type == notification_type)
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_failed(self, *, limit: int = 100) -> list[Notification]:
        """Return up to `limit` notifications that failed delivery, oldest-first."""
        return await self.list_by_delivery_status(
            NotificationDeliveryStatus.failed, limit=limit
        )

    async def list_older_than(self, cutoff: datetime) -> list[Notification]:
        """
        Return all notifications with created_at before `cutoff`.
        Used by the cleanup scheduler for 90-day retention enforcement.
        """
        stmt = (
            select(Notification)
            .where(Notification.created_at < cutoff)
            .order_by(Notification.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_paginated_by_status(
        self,
        status: NotificationDeliveryStatus,
        pagination: Pagination,
    ) -> PaginatedResult[Notification]:
        """Return a paginated list of notifications in the given delivery status."""
        return await self.list_paginated(
            pagination,
            Notification.delivery_status == status,
            order_by=Notification.created_at.desc(),
        )

    async def count_pending(self) -> int:
        """Return the total number of undelivered notifications."""
        return await self.count(
            Notification.delivery_status == NotificationDeliveryStatus.pending
        )

    async def count_failed_for_application(self, application_id: uuid.UUID) -> int:
        """Return the number of failed notifications for a given application."""
        return await self.count(
            and_(
                Notification.application_id == application_id,
                Notification.delivery_status == NotificationDeliveryStatus.failed,
            )
        )
