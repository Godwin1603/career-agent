import uuid
from datetime import datetime, timezone
from typing import ClassVar, List

from pydantic import BaseModel, Field

from src.core.enums import ApplicationStrategy, TaskType


class TaskPayload(BaseModel):
    """
    Payload dispatched to Cloud Tasks.
    """

    PAYLOAD_VERSION: ClassVar[str] = "v1"

    job_id: uuid.UUID
    task_type: TaskType
    retry_count: int = Field(default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload_version: str = Field(default=PAYLOAD_VERSION)


class RoutingResult(BaseModel):
    """
    Result of the routing engine evaluation.
    """

    strategies: List[ApplicationStrategy] = Field(default_factory=list)
    skipped: bool = Field(default=False)
