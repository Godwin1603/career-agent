"""
SQLAlchemy models for the applications domain.

Tables:
  - applications: one record per application attempt per strategy (permanent)
  - application_events: append-only audit log of every state transition (permanent)
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.enums import ApplicationStatus, ApplicationStrategy

if TYPE_CHECKING:
    from src.jobs.models import Job
    from src.notifications.models import Notification
    from src.resumes.models import ApplicationResume


class Application(Base):
    """
    One application record per (job, strategy) pair.
    A single job can generate up to three applications: portal, form, and email.
    """

    __tablename__ = "applications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    strategy: Mapped[ApplicationStrategy] = mapped_column(
        Enum(ApplicationStrategy, name="applicationstrategy", create_type=True),
        nullable=False,
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, name="applicationstatus", create_type=True),
        nullable=False,
        default=ApplicationStatus.pending,
        server_default=ApplicationStatus.pending.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    job: Mapped["Job"] = relationship("Job", back_populates="applications")
    events: Mapped[list["ApplicationEvent"]] = relationship(
        "ApplicationEvent",
        back_populates="application",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    application_resumes: Mapped[list["ApplicationResume"]] = relationship(
        "ApplicationResume",
        back_populates="application",
        cascade="all, delete-orphan",
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="application"
    )

    __table_args__ = (
        # Prevents duplicate application attempts for the same job + strategy
        UniqueConstraint("job_id", "strategy", name="uq_applications_job_strategy"),
        Index("ix_applications_status", "status"),
        Index("ix_applications_strategy", "strategy"),
        Index("ix_applications_updated_at", "updated_at"),
    )


class ApplicationEvent(Base):
    """
    Append-only event log for every state transition of an application.
    Never updated after creation. Retained indefinitely.
    """

    __tablename__ = "application_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    event_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    application: Mapped["Application"] = relationship(
        "Application", back_populates="events"
    )

    __table_args__ = (
        Index("ix_application_events_event_type", "event_type"),
        Index("ix_application_events_created_at", "created_at"),
    )
