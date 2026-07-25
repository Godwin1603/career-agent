import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.applications.dto import RoutingResult, TaskPayload
from src.applications.models import Application
from src.applications.services.dispatcher import TaskDispatcher
from src.core.cloud_tasks import (
    CloudTaskRetryableError,
    CloudTasksClient,
    CloudTaskTerminalError,
)
from src.core.enums import ApplicationStatus, ApplicationStrategy, TaskType
from src.jobs.models import Job


@pytest.fixture
def mock_session():
    session = AsyncMock()
    # Ensure flush is an async mock
    session.flush = AsyncMock()
    return session


@pytest.fixture
def mock_repo(monkeypatch):
    repo_mock = MagicMock()
    repo_mock.exists_for_job_and_strategy = AsyncMock(return_value=False)

    # We patch ApplicationRepository so that when instantiated in TaskDispatcher, it returns our mock
    # A cleaner way is to mock it on the dispatcher object after instantiation
    return repo_mock


@pytest.fixture
def mock_tasks_client():
    client = MagicMock(spec=CloudTasksClient)
    return client


@pytest.fixture
def dispatcher(mock_session, mock_tasks_client, mock_repo, monkeypatch):
    # Patch the ApplicationRepository class inside dispatcher module
    monkeypatch.setattr(
        "src.applications.services.dispatcher.ApplicationRepository",
        lambda session: mock_repo,
    )
    return TaskDispatcher(session=mock_session, tasks_client=mock_tasks_client)


@pytest.mark.asyncio
async def test_dispatch_skipped_job(dispatcher, mock_repo, mock_tasks_client):
    job = Job(id=uuid.uuid4())
    result = RoutingResult(skipped=True)

    await dispatcher.dispatch(job, result)

    # Should not add anything or enqueue
    assert mock_repo.add.call_count == 0
    assert mock_tasks_client.enqueue_portal.call_count == 0


@pytest.mark.asyncio
async def test_dispatch_no_strategies(dispatcher, mock_repo, mock_tasks_client):
    job = Job(id=uuid.uuid4())
    result = RoutingResult(strategies=[], skipped=False)

    await dispatcher.dispatch(job, result)

    assert mock_repo.add.call_count == 0
    assert mock_tasks_client.enqueue_portal.call_count == 0


@pytest.mark.asyncio
async def test_dispatch_duplicate_prevention(dispatcher, mock_repo, mock_tasks_client):
    job = Job(id=uuid.uuid4())
    result = RoutingResult(strategies=[ApplicationStrategy.portal], skipped=False)

    # Simulate an application already exists
    mock_repo.exists_for_job_and_strategy.return_value = True

    await dispatcher.dispatch(job, result)

    # Should not create a new one
    assert mock_repo.add.call_count == 0
    assert mock_tasks_client.enqueue_portal.call_count == 0


@pytest.mark.asyncio
async def test_dispatch_successful(dispatcher, mock_repo, mock_tasks_client):
    job = Job(id=uuid.uuid4())
    result = RoutingResult(
        strategies=[ApplicationStrategy.portal, ApplicationStrategy.email],
        skipped=False,
    )

    await dispatcher.dispatch(job, result)

    # Should add two applications
    assert mock_repo.add.call_count == 2

    added_apps = [call[0][0] for call in mock_repo.add.call_args_list]
    assert added_apps[0].strategy == ApplicationStrategy.portal
    assert added_apps[0].status == ApplicationStatus.pending

    assert added_apps[1].strategy == ApplicationStrategy.email
    assert added_apps[1].status == ApplicationStatus.pending

    # Should enqueue two tasks
    assert mock_tasks_client.enqueue_portal.call_count == 1
    assert mock_tasks_client.enqueue_email.call_count == 1

    portal_payload: TaskPayload = mock_tasks_client.enqueue_portal.call_args[0][0]
    assert portal_payload.job_id == job.id
    assert portal_payload.task_type == TaskType.portal_application
    assert portal_payload.retry_count == 0


@pytest.mark.asyncio
async def test_dispatch_retryable_error(dispatcher, mock_repo, mock_tasks_client):
    job = Job(id=uuid.uuid4())
    result = RoutingResult(strategies=[ApplicationStrategy.form], skipped=False)

    mock_tasks_client.enqueue_form.side_effect = CloudTaskRetryableError(
        "Network timeout"
    )

    await dispatcher.dispatch(job, result)

    # Error should be caught, application should remain pending
    added_app: Application = mock_repo.add.call_args[0][0]
    assert added_app.status == ApplicationStatus.pending
    # Retryable error should not set last_error per current implementation (or it could, but we don't assert it strictly)


@pytest.mark.asyncio
async def test_dispatch_terminal_error(dispatcher, mock_repo, mock_tasks_client):
    job = Job(id=uuid.uuid4())
    result = RoutingResult(strategies=[ApplicationStrategy.form], skipped=False)

    mock_tasks_client.enqueue_form.side_effect = CloudTaskTerminalError(
        "Invalid payload"
    )

    await dispatcher.dispatch(job, result)

    # Error should be caught, application should be marked failed
    added_app: Application = mock_repo.add.call_args[0][0]
    assert added_app.status == ApplicationStatus.failed
    assert added_app.last_error == "Invalid payload"


@pytest.mark.asyncio
async def test_dispatch_independent_failures(dispatcher, mock_repo, mock_tasks_client):
    job = Job(id=uuid.uuid4())
    result = RoutingResult(
        strategies=[ApplicationStrategy.portal, ApplicationStrategy.email],
        skipped=False,
    )

    # Portal fails terminally, but email should still proceed
    mock_tasks_client.enqueue_portal.side_effect = CloudTaskTerminalError("Terminal")

    await dispatcher.dispatch(job, result)

    assert mock_repo.add.call_count == 2
    assert mock_tasks_client.enqueue_portal.call_count == 1
    assert mock_tasks_client.enqueue_email.call_count == 1

    added_apps = [call[0][0] for call in mock_repo.add.call_args_list]
    assert added_apps[0].status == ApplicationStatus.failed
    assert added_apps[1].status == ApplicationStatus.pending
