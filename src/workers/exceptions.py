"""
Worker-specific exceptions.

Mirrors the retryable/terminal pattern from cloud_tasks.py
but scoped to strategy execution failures.
"""

from src.core.exceptions import CareerAgentException


class WorkerError(CareerAgentException):
    """Base exception for all worker errors."""

    pass


class WorkerRetryableError(WorkerError):
    """
    Temporary failure during strategy execution.
    Examples: external service timeout, temporary dependency unavailability.
    The application should transition to failed (retryable) and may be retried.
    """

    pass


class WorkerTerminalError(WorkerError):
    """
    Permanent failure during strategy execution.
    Examples: invalid payload, missing application, missing job,
    unsupported strategy.
    The application should transition to permanently_failed.
    """

    pass
