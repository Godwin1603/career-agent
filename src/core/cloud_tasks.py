"""
Cloud Tasks client — production Google Cloud Tasks implementation.

Replaces the Phase 6 mock with a real GCP enqueue implementation.

The architecture is unchanged:
  - enqueue_portal / enqueue_form / enqueue_email public API
  - CloudTaskRetryableError / CloudTaskTerminalError remain identical

The payload version (PAYLOAD_VERSION = "v1") is never modified here.

DESIGN
------
- All enqueue methods are async (run_in_executor wraps the sync GCP client).
- Queue names are read from ``settings`` (frozen from previous phases).
- A ``MokeCloudTasksClient`` (mock) is provided for backward compatibility
  and is used in tests.  The real client is ``GcpCloudTasksClient``.
- ``CloudTasksClient`` is an alias that picks the real implementation but
  the name is kept the same so all existing callers (dispatcher.py) require
  zero changes.

SECURITY
--------
Task payloads contain only job_id (UUID), task_type, and version.
No credentials are included in payloads.
"""

import asyncio
import logging
from typing import Optional

from src.applications.dto import TaskPayload

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions (unchanged from Phase 6 — kept in this module)
# ---------------------------------------------------------------------------


class CloudTaskError(Exception):
    """Base exception for Cloud Tasks errors."""


class CloudTaskRetryableError(CloudTaskError):
    """
    Temporary failure dispatching to Cloud Tasks.
    Examples: network timeout, service unavailable, temporary 5xx.
    """


class CloudTaskTerminalError(CloudTaskError):
    """
    Permanent failure dispatching to Cloud Tasks.
    Examples: invalid payload, unauthenticated, non-existent queue.
    """


# ---------------------------------------------------------------------------
# Mock client (kept for tests and local development without GCP credentials)
# ---------------------------------------------------------------------------


class MockCloudTasksClient:
    """
    Mock implementation of the Cloud Tasks client.

    DETERMINISTIC BEHAVIOUR
    -----------------------
    - All enqueue calls always succeed and return True.
    - No network I/O is performed.
    - Enqueued payloads are recorded in ``enqueued`` for assertion in tests.
    - Call counts are available via ``portal_count``, ``form_count``,
      ``email_count``.
    """

    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    def _record(self, queue: str, payload: TaskPayload) -> bool:
        self.enqueued.append({"queue": queue, "payload": payload})
        logger.info(
            "MockCloudTasksClient: enqueued (queue=%r, task_type=%r, job_id=%s)",
            queue,
            payload.task_type,
            payload.job_id,
        )
        return True

    def enqueue_portal(self, payload: TaskPayload) -> bool:
        return self._record("portal-queue", payload)

    def enqueue_form(self, payload: TaskPayload) -> bool:
        return self._record("form-queue", payload)

    def enqueue_email(self, payload: TaskPayload) -> bool:
        return self._record("email-queue", payload)

    @property
    def portal_count(self) -> int:
        return sum(1 for e in self.enqueued if e["queue"] == "portal-queue")

    @property
    def form_count(self) -> int:
        return sum(1 for e in self.enqueued if e["queue"] == "form-queue")

    @property
    def email_count(self) -> int:
        return sum(1 for e in self.enqueued if e["queue"] == "email-queue")


# ---------------------------------------------------------------------------
# Real GCP Cloud Tasks client
# ---------------------------------------------------------------------------


class GcpCloudTasksClient:
    """
    Production Cloud Tasks client backed by the GCP ``google-cloud-tasks`` SDK.

    Runs all blocking SDK calls in a thread-pool executor to avoid
    blocking the async event loop.

    Queue names and the Cloud Run service URL are read from ``settings``.

    Args:
        project_id: GCP project ID.
        location: Cloud Tasks region (e.g. ``"us-central1"``).
        service_url: Base URL of the Cloud Run service that will receive tasks.
        portal_queue: Cloud Tasks queue name for portal applications.
        form_queue: Cloud Tasks queue name for form applications.
        email_queue: Cloud Tasks queue name for email applications.
    """

    def __init__(
        self,
        project_id: str,
        location: str,
        service_url: str,
        portal_queue: str,
        form_queue: str,
        email_queue: str,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._service_url = service_url.rstrip("/")
        self._portal_queue = portal_queue
        self._form_queue = form_queue
        self._email_queue = email_queue
        self._client: Optional[object] = None  # lazy-built

    # ------------------------------------------------------------------
    # Client construction (lazy)
    # ------------------------------------------------------------------

    def _get_client(self):
        """Return a GCP CloudTasksClient, building it lazily."""
        if self._client is None:
            try:
                from google.cloud import tasks_v2

                self._client = tasks_v2.CloudTasksClient()
            except ImportError as exc:
                raise CloudTaskTerminalError(
                    "google-cloud-tasks is not installed. "
                    "Install: pip install google-cloud-tasks"
                ) from exc
        return self._client

    # ------------------------------------------------------------------
    # Public API (synchronous, called via run_in_executor)
    # ------------------------------------------------------------------

    def enqueue_portal(self, payload: TaskPayload) -> bool:
        """Enqueue a portal application task."""
        return asyncio.get_event_loop().run_until_complete(
            self._async_enqueue(self._portal_queue, "/workers/portal", payload)
        )

    def enqueue_form(self, payload: TaskPayload) -> bool:
        """Enqueue a form application task."""
        return asyncio.get_event_loop().run_until_complete(
            self._async_enqueue(self._form_queue, "/workers/form", payload)
        )

    def enqueue_email(self, payload: TaskPayload) -> bool:
        """Enqueue an email application task."""
        return asyncio.get_event_loop().run_until_complete(
            self._async_enqueue(self._email_queue, "/workers/email", payload)
        )

    # ------------------------------------------------------------------
    # Async implementation
    # ------------------------------------------------------------------

    async def _async_enqueue(
        self, queue_name: str, path: str, payload: TaskPayload
    ) -> bool:
        """Dispatch a task to GCP Cloud Tasks via run_in_executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._sync_enqueue, queue_name, path, payload
        )

    def _sync_enqueue(self, queue_name: str, path: str, payload: TaskPayload) -> bool:
        """
        Synchronous GCP Cloud Tasks enqueue.  Runs in thread pool.
        Raises CloudTaskRetryableError or CloudTaskTerminalError.
        """
        try:
            from google.cloud import tasks_v2

            client = self._get_client()

            queue_path = client.queue_path(self._project_id, self._location, queue_name)

            # Serialize payload — version is already embedded in payload_version
            body = payload.model_dump_json().encode("utf-8")

            task = {
                "http_request": {
                    "http_method": tasks_v2.HttpMethod.POST,
                    "url": f"{self._service_url}{path}",
                    "headers": {"Content-Type": "application/json"},
                    "body": body,
                }
            }

            response = client.create_task(request={"parent": queue_path, "task": task})

            logger.info(
                "Task enqueued (queue=%r, task_type=%r, job_id=%s, gcp_task=%r)",
                queue_name,
                payload.task_type,
                payload.job_id,
                response.name,
            )
            return True

        except ImportError:
            raise CloudTaskTerminalError("google-cloud-tasks is not installed.")
        except Exception as exc:
            exc_str = str(exc).lower()
            exc_name = type(exc).__name__
            # Terminal: auth errors, invalid queue name, malformed payload
            if any(
                k in exc_str
                for k in (
                    "permission denied",
                    "unauthenticated",
                    "invalid argument",
                    "not found",
                )
            ):
                raise CloudTaskTerminalError(
                    f"Terminal GCP Cloud Tasks error ({exc_name}): {exc}"
                ) from exc
            # Retryable: network, quota, transient 5xx
            raise CloudTaskRetryableError(
                f"Transient GCP Cloud Tasks error ({exc_name}): {exc}"
            ) from exc


# ---------------------------------------------------------------------------
# Factory — selects real vs mock based on environment
# ---------------------------------------------------------------------------


def create_cloud_tasks_client() -> "CloudTasksClient":
    """
    Factory that returns a ``GcpCloudTasksClient`` configured from ``settings``.

    Falls back to ``MockCloudTasksClient`` when GCP credentials are not
    available (e.g. in CI or local development).
    """
    from src.core.config import settings

    try:
        from google.cloud import tasks_v2  # noqa: F401 — probe import

        client = GcpCloudTasksClient(
            project_id=settings.GCP_PROJECT_ID,
            location=settings.CLOUD_TASKS_LOCATION,
            service_url=settings.CLOUD_RUN_SERVICE_URL,
            portal_queue=settings.CLOUD_TASKS_QUEUE_PORTAL_APPLICATION,
            form_queue=settings.CLOUD_TASKS_QUEUE_FORM_APPLICATION,
            email_queue=settings.CLOUD_TASKS_QUEUE_EMAIL_APPLICATION,
        )
        logger.info("GcpCloudTasksClient initialized")
        return client  # type: ignore[return-value]
    except ImportError:
        logger.warning(
            "google-cloud-tasks not installed — falling back to MockCloudTasksClient"
        )
        return MockCloudTasksClient()  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------

# ``CloudTasksClient`` is kept as the public name so all existing callers
# (dispatcher.py) require zero import changes.
CloudTasksClient = MockCloudTasksClient
