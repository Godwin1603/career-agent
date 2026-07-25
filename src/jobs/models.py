"""
SQLAlchemy models for the jobs domain.

Tables:
  - job_raw_messages: raw Telegram message text before AI processing (30-day retention)
  - jobs: structured, AI-enriched job postings (permanent)
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.enums import JobStatus, RawMessageStatus

if TYPE_CHECKING:
    from src.applications.models import Application
    from src.notifications.models import Notification
    from src.resumes.models import Resume


class JobRawMessage(Base):
    """
    Raw, unprocessed Telegram message before AI parsing.
    Retained for 30 days for debugging and re-processing.
    Each raw message may produce 0 or more parsed Jobs (1:many).
    """

    __tablename__ = "job_raw_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_message_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True
    )
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[RawMessageStatus] = mapped_column(
        Enum(RawMessageStatus, name="rawmessagestatus", create_type=True),
        nullable=False,
        default=RawMessageStatus.pending,
        server_default=RawMessageStatus.pending.value,
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
    jobs: Mapped[list["Job"]] = relationship(
        "Job", back_populates="raw_message", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "telegram_message_id",
            "channel_id",
            name="uq_job_raw_messages_telegram_message_channel",
        ),
        Index("ix_job_raw_messages_status", "status"),
        Index("ix_job_raw_messages_created_at", "created_at"),
    )


class Job(Base):
    """
    Structured, AI-enriched job posting. The central entity of the system.
    One job is linked to exactly one raw message source; one raw message may
    produce multiple jobs if the message contained multiple postings.
    """

    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    raw_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("job_raw_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # AI-extracted fields
    company_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_remote: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    application_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email_address: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    google_form_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    salary_range: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    relevance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detected_portal: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Processing state
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="jobstatus", create_type=True),
        nullable=False,
        default=JobStatus.pending,
        server_default=JobStatus.pending.value,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    raw_message: Mapped[Optional["JobRawMessage"]] = relationship(
        "JobRawMessage", back_populates="jobs"
    )
    applications: Mapped[list["Application"]] = relationship(
        "Application", back_populates="job", cascade="all, delete-orphan"
    )
    resumes: Mapped[list["Resume"]] = relationship("Resume", back_populates="job")
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="job"
    )

    __table_args__ = (
        Index("ix_jobs_status", "status"),
        Index("ix_jobs_relevance_score", "relevance_score"),
        Index("ix_jobs_created_at", "created_at"),
        Index("ix_jobs_expires_at", "expires_at"),
        Index("ix_jobs_detected_portal", "detected_portal"),
    )
