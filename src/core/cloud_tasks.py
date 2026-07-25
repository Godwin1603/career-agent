import logging

from src.applications.dto import TaskPayload

logger = logging.getLogger(__name__)


class CloudTaskError(Exception):
    """Base exception for Cloud Tasks errors."""

    pass


class CloudTaskRetryableError(CloudTaskError):
    """
    Temporary failure dispatching to Cloud Tasks.
    Examples: network timeout, service unavailable, temporary 5xx.
    """

    pass


class CloudTaskTerminalError(CloudTaskError):
    """
    Permanent failure dispatching to Cloud Tasks.
    Examples: invalid payload, unauthenticated, non-existent queue.
    """

    pass


class CloudTasksClient:
    """
    Abstraction over Google Cloud Tasks.
    Currently mocked as per Phase 6 requirements.
    """

    def _enqueue(self, queue_name: str, payload: TaskPayload) -> bool:
        """
        Internal mock enqueue method.
        """
        logger.info(
            f"Mock dispatching task {payload.task_type} for job {payload.job_id} to queue {queue_name}"
        )
        # Mock implementation always succeeds
        return True

    def enqueue_portal(self, payload: TaskPayload) -> bool:
        return self._enqueue("portal-queue", payload)

    def enqueue_form(self, payload: TaskPayload) -> bool:
        return self._enqueue("form-queue", payload)

    def enqueue_email(self, payload: TaskPayload) -> bool:
        return self._enqueue("email-queue", payload)
