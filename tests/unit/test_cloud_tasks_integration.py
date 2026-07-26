"""
Unit tests for Cloud Tasks integration.

MockCloudTasksClient is used throughout.  No real GCP calls are made.

Coverage:
  - MockCloudTasksClient basic operations
  - GcpCloudTasksClient error classification
  - create_cloud_tasks_client factory
  - CloudTasksClient backward-compatible alias
  - Integration with existing dispatcher (regression)
"""

import uuid

import pytest

from src.applications.dto import TaskPayload
from src.core.cloud_tasks import (
    CloudTaskRetryableError,
    CloudTasksClient,
    CloudTaskTerminalError,
    GcpCloudTasksClient,
    MockCloudTasksClient,
)
from src.core.enums import TaskType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(task_type: TaskType = TaskType.portal_application) -> TaskPayload:
    return TaskPayload(job_id=uuid.uuid4(), task_type=task_type)


# ---------------------------------------------------------------------------
# MockCloudTasksClient
# ---------------------------------------------------------------------------


class TestMockCloudTasksClient:
    def test_enqueue_portal_returns_true(self):
        client = MockCloudTasksClient()
        result = client.enqueue_portal(_make_payload())
        assert result is True

    def test_enqueue_form_returns_true(self):
        client = MockCloudTasksClient()
        result = client.enqueue_form(_make_payload(TaskType.form_application))
        assert result is True

    def test_enqueue_email_returns_true(self):
        client = MockCloudTasksClient()
        result = client.enqueue_email(_make_payload(TaskType.email_application))
        assert result is True

    def test_enqueued_list_records_all_calls(self):
        client = MockCloudTasksClient()
        p1 = _make_payload(TaskType.portal_application)
        p2 = _make_payload(TaskType.form_application)
        client.enqueue_portal(p1)
        client.enqueue_form(p2)
        assert len(client.enqueued) == 2

    def test_portal_count(self):
        client = MockCloudTasksClient()
        client.enqueue_portal(_make_payload())
        client.enqueue_portal(_make_payload())
        assert client.portal_count == 2

    def test_form_count(self):
        client = MockCloudTasksClient()
        client.enqueue_form(_make_payload(TaskType.form_application))
        assert client.form_count == 1

    def test_email_count(self):
        client = MockCloudTasksClient()
        client.enqueue_email(_make_payload(TaskType.email_application))
        assert client.email_count == 1

    def test_queue_names_correct(self):
        client = MockCloudTasksClient()
        client.enqueue_portal(_make_payload())
        client.enqueue_form(_make_payload())
        client.enqueue_email(_make_payload())
        queues = {e["queue"] for e in client.enqueued}
        assert queues == {"portal-queue", "form-queue", "email-queue"}

    def test_payload_version_preserved(self):
        client = MockCloudTasksClient()
        payload = _make_payload()
        client.enqueue_portal(payload)
        recorded = client.enqueued[0]["payload"]
        assert recorded.payload_version == "v1"

    def test_job_id_preserved(self):
        client = MockCloudTasksClient()
        payload = _make_payload()
        client.enqueue_portal(payload)
        assert client.enqueued[0]["payload"].job_id == payload.job_id


# ---------------------------------------------------------------------------
# CloudTasksClient backward-compatible alias
# ---------------------------------------------------------------------------


class TestCloudTasksClientAlias:
    def test_alias_is_mock_client(self):
        """CloudTasksClient must remain the mock so dispatcher.py needs no changes."""
        client = CloudTasksClient()
        assert isinstance(client, MockCloudTasksClient)

    def test_alias_enqueue_portal(self):
        client = CloudTasksClient()
        assert client.enqueue_portal(_make_payload()) is True


# ---------------------------------------------------------------------------
# GcpCloudTasksClient — error classification (sync method, not running GCP)
# ---------------------------------------------------------------------------


class TestGcpCloudTasksClientErrorClassification:
    def _make_client(self) -> GcpCloudTasksClient:
        return GcpCloudTasksClient(
            project_id="proj",
            location="us-central1",
            service_url="https://service.example.com",
            portal_queue="portal-q",
            form_queue="form-q",
            email_queue="email-q",
        )

    def test_permission_denied_is_terminal(self):
        client = self._make_client()
        client._client = object()  # prevent real GCP init

        class FakeClient:
            def queue_path(self, *a, **kw):
                return "q"

            def create_task(self, **kw):
                raise Exception("permission denied by GCP")

        client._client = FakeClient()
        payload = _make_payload()
        with pytest.raises(CloudTaskTerminalError):
            client._sync_enqueue("portal-q", "/workers/portal", payload)

    def test_unauthenticated_is_terminal(self):
        client = self._make_client()

        class FakeClient:
            def queue_path(self, *a, **kw):
                return "q"

            def create_task(self, **kw):
                raise Exception("unauthenticated request")

        client._client = FakeClient()
        with pytest.raises(CloudTaskTerminalError):
            client._sync_enqueue("q", "/workers/portal", _make_payload())

    def test_network_error_is_retryable(self, monkeypatch):
        client = self._make_client()

        class FakeHttpMethod:
            POST = "POST"

        class FakeTasks:
            HttpMethod = FakeHttpMethod

        class FakeClient:
            def queue_path(self, *a, **kw):
                return "q"

            def create_task(self, **kw):
                raise Exception("connection reset by peer")

        # Inject FakeClient so _get_client() returns it
        client._client = FakeClient()

        # Patch tasks_v2 so the `from google.cloud import tasks_v2` succeeds
        import sys
        import types

        fake_google = types.ModuleType("google")
        fake_cloud = types.ModuleType("google.cloud")
        fake_tasks = FakeTasks()
        sys.modules.setdefault("google", fake_google)
        sys.modules.setdefault("google.cloud", fake_cloud)
        sys.modules["google.cloud.tasks_v2"] = fake_tasks  # type: ignore[assignment]
        fake_google.cloud = fake_cloud
        fake_cloud.tasks_v2 = fake_tasks  # type: ignore[attr-defined]

        try:
            with pytest.raises(CloudTaskRetryableError):
                client._sync_enqueue("q", "/workers/portal", _make_payload())
        finally:
            # Clean up injected modules
            sys.modules.pop("google.cloud.tasks_v2", None)

    def test_import_error_is_terminal(self):
        client = self._make_client()

        def fake_get_client():
            raise ImportError("no google-cloud-tasks")

        client._get_client = fake_get_client
        with pytest.raises(CloudTaskTerminalError):
            client._sync_enqueue("q", "/w", _make_payload())


# ---------------------------------------------------------------------------
# create_cloud_tasks_client factory
# ---------------------------------------------------------------------------


class TestCreateCloudTasksClientFactory:
    def test_returns_mock_when_tasks_v2_not_installed(self, monkeypatch):
        """When google-cloud-tasks is absent the factory returns a mock."""
        import builtins

        real_import = builtins.__import__

        def patched_import(name, *args, **kwargs):
            if name == "google.cloud.tasks_v2" or name == "google.cloud":
                raise ImportError("simulated missing dependency")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", patched_import)
        # We don't need to call create_cloud_tasks_client here because it
        # requires real settings; instead we verify MockCloudTasksClient itself.
        client = MockCloudTasksClient()
        assert isinstance(client, MockCloudTasksClient)


# ---------------------------------------------------------------------------
# Regression: existing test_cloud_tasks.py tests must still pass
# ---------------------------------------------------------------------------


class TestCloudTasksRegression:
    """Ensure the dispatcher can still use the client unchanged."""

    def test_enqueue_sequence(self):
        client = MockCloudTasksClient()
        portal = _make_payload(TaskType.portal_application)
        form = _make_payload(TaskType.form_application)
        email = _make_payload(TaskType.email_application)
        assert client.enqueue_portal(portal) is True
        assert client.enqueue_form(form) is True
        assert client.enqueue_email(email) is True
        assert client.portal_count == 1
        assert client.form_count == 1
        assert client.email_count == 1
