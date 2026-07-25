"""
SQLAlchemy model for task_log.

Table:
  - task_log: tracks every Cloud Task dispatched by the system (60-day retention)
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base
from src.core.enums import TaskStatus, TaskType


class TaskLog(Base):
    """
    Operational log of every Cloud Task dispatched by the system.
    Used for idempotency checks and debugging task delivery failures.
    Entries older than 60 days are purged by the cleanup scheduler.
    """

    __tablename__ = "task_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Cloud Tasks task name — globally unique, used for idempotency deduplication
    cloud_task_name: Mapped[str] = mapped_column(
        String(500), nullable=False, unique=True, index=True
    )
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, name="tasktype", create_type=True),
        nullable=False,
    )
    # The entity this task operates on (job_id or application_id as a string)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="taskstatus", create_type=True),
        nullable=False,
        default=TaskStatus.pending,
        server_default=TaskStatus.pending.value,
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_task_log_task_type", "task_type"),
        Index("ix_task_log_status", "status"),
        Index("ix_task_log_entity_id_task_type", "entity_id", "task_type"),
    )
