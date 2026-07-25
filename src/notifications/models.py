"""
SQLAlchemy model for the notifications domain.

Table:
  - notifications: every notification dispatched to the user (90-day retention)
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.enums import NotificationDeliveryStatus, NotificationType

if TYPE_CHECKING:
    from src.applications.models import Application
    from src.jobs.models import Job


class Notification(Base):
    """
    Records every notification dispatched to the user, including delivery status.

    Both FK columns are nullable to accommodate:
      - Job-level notifications (job_id set, application_id None)
      - Application-level notifications (both FKs set)
      - System-level alerts (both FKs None — e.g. dead-letter exhaustion)
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    application_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notificationtype", create_type=True),
        nullable=False,
    )
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    delivery_status: Mapped[NotificationDeliveryStatus] = mapped_column(
        Enum(
            NotificationDeliveryStatus,
            name="notificationdeliverystatus",
            create_type=True,
        ),
        nullable=False,
        default=NotificationDeliveryStatus.pending,
        server_default=NotificationDeliveryStatus.pending.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    job: Mapped[Optional["Job"]] = relationship("Job", back_populates="notifications")
    application: Mapped[Optional["Application"]] = relationship(
        "Application", back_populates="notifications"
    )

    __table_args__ = (
        Index("ix_notifications_delivery_status", "delivery_status"),
        Index("ix_notifications_notification_type", "notification_type"),
        Index("ix_notifications_created_at", "created_at"),
    )
