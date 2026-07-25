"""
DTOs for the worker layer.

WorkerContext carries all entities needed during a strategy execution.
WorkerResult captures the outcome for persistence.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.applications.models import Application
from src.jobs.models import Job
from src.resumes.models import Resume


class WorkerOutcome(str, Enum):
    """Possible outcomes of a worker strategy execution."""

    success = "success"
    retryable_failure = "retryable_failure"
    terminal_failure = "terminal_failure"


class WorkerResult(BaseModel):
    """
    Result of a single strategy execution.
    Used by the base worker to determine state transitions and event recording.
    """

    model_config = {"arbitrary_types_allowed": True}

    outcome: WorkerOutcome
    error_message: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class WorkerContext:
    """
    Holds the loaded entities required for executing a strategy.
    Passed to the strategy abstraction by the base worker.
    """

    __slots__ = ("application", "job", "resume")

    def __init__(
        self,
        application: Application,
        job: Job,
        resume: Optional[Resume] = None,
    ) -> None:
        self.application = application
        self.job = job
        self.resume = resume
