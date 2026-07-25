"""
SQLAlchemy models for the resumes domain.

Tables:
  - resumes: tracks every resume version (base or tailored). Permanent.
  - application_resumes: join table linking an application to the resume used for it.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.core.enums import ResumeLabel

if TYPE_CHECKING:
    from src.applications.models import Application
    from src.jobs.models import Job


class Resume(Base):
    """
    Every resume version generated or used by the system.
    Base resumes have no associated job.
    Tailored resumes reference the job they were generated for.
    """

    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    label: Mapped[ResumeLabel] = mapped_column(
        Enum(ResumeLabel, name="resumelabel", create_type=True),
        nullable=False,
    )
    job_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # GCS path (e.g. resumes/base/resume.pdf or resumes/{job_id}/tailored.pdf)
    gcs_path: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 hash — used to detect stale tailored resumes when base changes
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
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
    job: Mapped[Optional["Job"]] = relationship("Job", back_populates="resumes")
    application_resumes: Mapped[list["ApplicationResume"]] = relationship(
        "ApplicationResume",
        back_populates="resume",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_resumes_label", "label"),
        Index("ix_resumes_content_hash", "content_hash"),
    )


class ApplicationResume(Base):
    """
    Join table linking a specific application to the resume version used for it.
    One application uses exactly one resume version.
    """

    __tablename__ = "application_resumes"

    application_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("applications.id", ondelete="CASCADE"),
        primary_key=True,
    )
    resume_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("resumes.id", ondelete="RESTRICT"),
        primary_key=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    application: Mapped["Application"] = relationship(
        "Application", back_populates="application_resumes"
    )
    resume: Mapped["Resume"] = relationship(
        "Resume", back_populates="application_resumes"
    )
