import uuid
from datetime import datetime, timezone

from src.applications.dto import TaskPayload
from src.core.cloud_tasks import CloudTasksClient
from src.core.enums import TaskType


def test_enqueue_portal_success():
    client = CloudTasksClient()
    payload = TaskPayload(
        job_id=uuid.uuid4(),
        task_type=TaskType.portal_application,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )
    # The mock client should return True
    result = client.enqueue_portal(payload)
    assert result is True


def test_enqueue_form_success():
    client = CloudTasksClient()
    payload = TaskPayload(
        job_id=uuid.uuid4(),
        task_type=TaskType.form_application,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )
    result = client.enqueue_form(payload)
    assert result is True


def test_enqueue_email_success():
    client = CloudTasksClient()
    payload = TaskPayload(
        job_id=uuid.uuid4(),
        task_type=TaskType.email_application,
        retry_count=0,
        created_at=datetime.now(timezone.utc),
    )
    result = client.enqueue_email(payload)
    assert result is True
