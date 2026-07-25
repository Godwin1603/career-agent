"""
Unit tests for Phase 7 application workers.

Tests cover:
  - All three workers (portal, form, email)
  - Success path
  - Retryable failure
  - Terminal failure
  - Missing application
  - Missing job
  - Resume manager (tailored + base fallback + no resume)
  - State transitions (pending → in_progress → success/failed/permanently_failed)
  - ApplicationEvent recording
  - Non-processable application state rejection
  - Regression tests for base worker lifecycle
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

import src.core.model_registry  # noqa: F401
from src.applications.models import Application, ApplicationEvent
from src.core.enums import ApplicationStatus, ApplicationStrategy
from src.core.exceptions import EntityNotFound
from src.jobs.models import Job
from src.resumes.models import Resume
from src.workers.dto import WorkerContext, WorkerOutcome, WorkerResult
from src.workers.email_worker import EmailWorker
from src.workers.exceptions import WorkerRetryableError, WorkerTerminalError
from src.workers.form_worker import GoogleFormWorker
from src.workers.portal_worker import PortalWorker
from src.workers.strategies import BaseStrategy

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.flush = AsyncMock()
    # begin_nested support for savepoint patterns
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__.return_value = None
    mock_ctx.__aexit__.return_value = None
    session.begin_nested = MagicMock(return_value=mock_ctx)
    return session


@pytest.fixture
def job_id():
    return uuid.uuid4()


@pytest.fixture
def make_application(job_id):
    def _make(
        status: ApplicationStatus = ApplicationStatus.pending,
        strategy: ApplicationStrategy = ApplicationStrategy.portal,
    ) -> Application:
        app = Application(
            job_id=job_id,
            strategy=strategy,
            status=status,
            attempt_count=0,
        )
        return app

    return _make


@pytest.fixture
def make_job(job_id):
    def _make() -> Job:
        job = Job(
            id=job_id,
            company_name="Test Corp",
            role_title="Senior Engineer",
            application_url="https://portal.example.com/apply",
            email_address="jobs@test.com",
            google_form_url="https://forms.google.com/d/abc",
        )
        return job

    return _make


@pytest.fixture
def make_resume():
    def _make() -> Resume:
        resume = Resume(
            gcs_path="resumes/base/resume.pdf",
            content_hash="abc123",
            label="base",
        )
        return resume

    return _make


class MockStrategy(BaseStrategy):
    """Test strategy that returns a configurable result."""

    def __init__(self, result: WorkerResult):
        self._result = result

    async def execute(self, context: WorkerContext) -> WorkerResult:
        return self._result


class FailingStrategy(BaseStrategy):
    """Test strategy that raises a configurable exception."""

    def __init__(self, exception: Exception):
        self._exception = exception

    async def execute(self, context: WorkerContext) -> WorkerResult:
        raise self._exception


def _patch_repos(
    monkeypatch,
    application=None,
    job=None,
    tailored_resume=None,
    base_resume=None,
    app_not_found=False,
    job_not_found=False,
):
    """Patch all repository methods used by the base worker."""
    if app_not_found:
        app_get = AsyncMock(return_value=None)
    else:
        app_get = AsyncMock(return_value=application)

    if job_not_found:
        job_get = AsyncMock(side_effect=EntityNotFound("Job", "missing-id"))
    else:
        job_get = AsyncMock(return_value=job)

    monkeypatch.setattr(
        "src.workers.base.ApplicationRepository.get_by_job_and_strategy",
        app_get,
    )
    monkeypatch.setattr(
        "src.workers.base.JobRepository.get_by_id",
        job_get,
    )
    monkeypatch.setattr(
        "src.workers.base.ResumeRepository.get_tailored_for_job",
        AsyncMock(return_value=tailored_resume),
    )
    monkeypatch.setattr(
        "src.workers.base.ResumeRepository.get_base_resume",
        AsyncMock(return_value=base_resume),
    )
    # add() is inherited from BaseRepository, so we patch it there
    monkeypatch.setattr(
        "src.workers.base.ApplicationEventRepository.add",
        MagicMock(),
        raising=False,
    )


# ---------------------------------------------------------------------------
# Portal Worker Tests
# ---------------------------------------------------------------------------


class TestPortalWorker:
    @pytest.mark.asyncio
    async def test_success_path(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        resume = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=MockStrategy(success_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.success
        assert app.status == ApplicationStatus.success
        assert app.applied_at is not None
        assert app.last_error is None
        assert app.attempt_count == 1

    @pytest.mark.asyncio
    async def test_retryable_failure(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        resume = make_resume()
        retry_result = WorkerResult(
            outcome=WorkerOutcome.retryable_failure,
            error_message="Portal timeout",
        )

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=MockStrategy(retry_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert app.status == ApplicationStatus.failed
        assert app.last_error == "Portal timeout"

    @pytest.mark.asyncio
    async def test_terminal_failure(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        resume = make_resume()
        terminal_result = WorkerResult(
            outcome=WorkerOutcome.terminal_failure,
            error_message="Unsupported portal",
        )

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=MockStrategy(terminal_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert app.status == ApplicationStatus.permanently_failed
        assert app.last_error == "Unsupported portal"

    @pytest.mark.asyncio
    async def test_missing_application(self, mock_session, job_id, monkeypatch):
        _patch_repos(monkeypatch, app_not_found=True)

        worker = PortalWorker(session=mock_session)
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "Application not found" in result.error_message

    @pytest.mark.asyncio
    async def test_missing_job(
        self, mock_session, job_id, make_application, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        _patch_repos(monkeypatch, application=app, job_not_found=True)

        worker = PortalWorker(session=mock_session)
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "Job not found" in result.error_message

    @pytest.mark.asyncio
    async def test_strategy_raises_retryable(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        resume = make_resume()

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=FailingStrategy(WorkerRetryableError("Connection reset")),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert app.status == ApplicationStatus.failed

    @pytest.mark.asyncio
    async def test_strategy_raises_terminal(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        resume = make_resume()

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=FailingStrategy(WorkerTerminalError("Invalid selector")),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert app.status == ApplicationStatus.permanently_failed


# ---------------------------------------------------------------------------
# Google Form Worker Tests
# ---------------------------------------------------------------------------


class TestGoogleFormWorker:
    @pytest.mark.asyncio
    async def test_success_path(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.form)
        job = make_job()
        resume = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = GoogleFormWorker(
            session=mock_session,
            strategy=MockStrategy(success_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.success
        assert app.status == ApplicationStatus.success

    @pytest.mark.asyncio
    async def test_retryable_failure(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.form)
        job = make_job()
        resume = make_resume()
        retry_result = WorkerResult(
            outcome=WorkerOutcome.retryable_failure,
            error_message="Form page timed out",
        )

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = GoogleFormWorker(
            session=mock_session,
            strategy=MockStrategy(retry_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert app.status == ApplicationStatus.failed

    @pytest.mark.asyncio
    async def test_terminal_failure(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.form)
        job = make_job()
        resume = make_resume()
        terminal_result = WorkerResult(
            outcome=WorkerOutcome.terminal_failure,
            error_message="Form closed",
        )

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = GoogleFormWorker(
            session=mock_session,
            strategy=MockStrategy(terminal_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert app.status == ApplicationStatus.permanently_failed

    @pytest.mark.asyncio
    async def test_missing_application(self, mock_session, job_id, monkeypatch):
        _patch_repos(monkeypatch, app_not_found=True)

        worker = GoogleFormWorker(session=mock_session)
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure

    @pytest.mark.asyncio
    async def test_missing_job(
        self, mock_session, job_id, make_application, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.form)
        _patch_repos(monkeypatch, application=app, job_not_found=True)

        worker = GoogleFormWorker(session=mock_session)
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure


# ---------------------------------------------------------------------------
# Email Worker Tests
# ---------------------------------------------------------------------------


class TestEmailWorker:
    @pytest.mark.asyncio
    async def test_success_path(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.email)
        job = make_job()
        resume = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = EmailWorker(
            session=mock_session,
            strategy=MockStrategy(success_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.success
        assert app.status == ApplicationStatus.success
        assert app.applied_at is not None

    @pytest.mark.asyncio
    async def test_retryable_failure(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.email)
        job = make_job()
        resume = make_resume()
        retry_result = WorkerResult(
            outcome=WorkerOutcome.retryable_failure,
            error_message="Gmail rate limited",
        )

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = EmailWorker(
            session=mock_session,
            strategy=MockStrategy(retry_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert app.status == ApplicationStatus.failed
        assert app.last_error == "Gmail rate limited"

    @pytest.mark.asyncio
    async def test_terminal_failure(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.email)
        job = make_job()
        resume = make_resume()
        terminal_result = WorkerResult(
            outcome=WorkerOutcome.terminal_failure,
            error_message="Invalid email address",
        )

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = EmailWorker(
            session=mock_session,
            strategy=MockStrategy(terminal_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert app.status == ApplicationStatus.permanently_failed

    @pytest.mark.asyncio
    async def test_missing_application(self, mock_session, job_id, monkeypatch):
        _patch_repos(monkeypatch, app_not_found=True)

        worker = EmailWorker(session=mock_session)
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure

    @pytest.mark.asyncio
    async def test_missing_job(
        self, mock_session, job_id, make_application, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.email)
        _patch_repos(monkeypatch, application=app, job_not_found=True)

        worker = EmailWorker(session=mock_session)
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure


# ---------------------------------------------------------------------------
# Resume Manager Tests
# ---------------------------------------------------------------------------


class TestResumeManager:
    @pytest.mark.asyncio
    async def test_tailored_resume_preferred(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        tailored = make_resume()
        base = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(
            monkeypatch,
            application=app,
            job=job,
            tailored_resume=tailored,
            base_resume=base,
        )

        # Track which resume is passed to the strategy
        captured_context = []

        class CapturingStrategy(BaseStrategy):
            async def execute(self, context: WorkerContext) -> WorkerResult:
                captured_context.append(context)
                return success_result

        worker = PortalWorker(
            session=mock_session,
            strategy=CapturingStrategy(),
        )
        await worker.execute(job_id)

        assert len(captured_context) == 1
        assert captured_context[0].resume is tailored

    @pytest.mark.asyncio
    async def test_base_resume_fallback(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        base = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(
            monkeypatch,
            application=app,
            job=job,
            tailored_resume=None,
            base_resume=base,
        )

        captured_context = []

        class CapturingStrategy(BaseStrategy):
            async def execute(self, context: WorkerContext) -> WorkerResult:
                captured_context.append(context)
                return success_result

        worker = PortalWorker(
            session=mock_session,
            strategy=CapturingStrategy(),
        )
        await worker.execute(job_id)

        assert len(captured_context) == 1
        assert captured_context[0].resume is base

    @pytest.mark.asyncio
    async def test_no_resume_available(
        self, mock_session, job_id, make_application, make_job, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(
            monkeypatch,
            application=app,
            job=job,
            tailored_resume=None,
            base_resume=None,
        )

        captured_context = []

        class CapturingStrategy(BaseStrategy):
            async def execute(self, context: WorkerContext) -> WorkerResult:
                captured_context.append(context)
                return success_result

        worker = PortalWorker(
            session=mock_session,
            strategy=CapturingStrategy(),
        )
        await worker.execute(job_id)

        assert len(captured_context) == 1
        assert captured_context[0].resume is None


# ---------------------------------------------------------------------------
# State Transition Tests
# ---------------------------------------------------------------------------


class TestStateTransitions:
    @pytest.mark.asyncio
    async def test_pending_to_in_progress_to_success(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(
            status=ApplicationStatus.pending,
            strategy=ApplicationStrategy.portal,
        )
        job = make_job()
        resume = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=MockStrategy(success_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.success
        assert app.status == ApplicationStatus.success
        assert app.attempt_count == 1

    @pytest.mark.asyncio
    async def test_pending_to_in_progress_to_failed(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(
            status=ApplicationStatus.pending,
            strategy=ApplicationStrategy.form,
        )
        job = make_job()
        resume = make_resume()
        retry_result = WorkerResult(
            outcome=WorkerOutcome.retryable_failure,
            error_message="Timeout",
        )

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = GoogleFormWorker(
            session=mock_session,
            strategy=MockStrategy(retry_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert app.status == ApplicationStatus.failed

    @pytest.mark.asyncio
    async def test_pending_to_in_progress_to_permanently_failed(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(
            status=ApplicationStatus.pending,
            strategy=ApplicationStrategy.email,
        )
        job = make_job()
        resume = make_resume()
        terminal_result = WorkerResult(
            outcome=WorkerOutcome.terminal_failure,
            error_message="Invalid",
        )

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = EmailWorker(
            session=mock_session,
            strategy=MockStrategy(terminal_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert app.status == ApplicationStatus.permanently_failed

    @pytest.mark.asyncio
    async def test_failed_application_can_be_retried(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        """A previously failed application should be re-processable."""
        app = make_application(
            status=ApplicationStatus.failed,
            strategy=ApplicationStrategy.portal,
        )
        job = make_job()
        resume = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=MockStrategy(success_result),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.success
        assert app.status == ApplicationStatus.success

    @pytest.mark.asyncio
    async def test_non_processable_state_rejected(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        """Applications in success state should not be re-processed."""
        app = make_application(
            status=ApplicationStatus.success,
            strategy=ApplicationStrategy.portal,
        )
        job = make_job()
        resume = make_resume()

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(session=mock_session)
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "non-processable state" in result.error_message

    @pytest.mark.asyncio
    async def test_permanently_failed_state_rejected(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        """Applications in permanently_failed state should not be re-processed."""
        app = make_application(
            status=ApplicationStatus.permanently_failed,
            strategy=ApplicationStrategy.portal,
        )
        job = make_job()
        resume = make_resume()

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(session=mock_session)
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "non-processable state" in result.error_message


# ---------------------------------------------------------------------------
# ApplicationEvent Recording Tests
# ---------------------------------------------------------------------------


class TestApplicationEvents:
    @pytest.mark.asyncio
    async def test_events_recorded_on_success(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        resume = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        event_add_mock = MagicMock()
        monkeypatch.setattr(
            "src.workers.base.ApplicationRepository.get_by_job_and_strategy",
            AsyncMock(return_value=app),
        )
        monkeypatch.setattr(
            "src.workers.base.JobRepository.get_by_id",
            AsyncMock(return_value=job),
        )
        monkeypatch.setattr(
            "src.workers.base.ResumeRepository.get_tailored_for_job",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "src.workers.base.ResumeRepository.get_base_resume",
            AsyncMock(return_value=resume),
        )
        monkeypatch.setattr(
            "src.workers.base.ApplicationEventRepository.add",
            event_add_mock,
            raising=False,
        )

        worker = PortalWorker(
            session=mock_session,
            strategy=MockStrategy(success_result),
        )
        await worker.execute(job_id)

        # Two events should be recorded:
        # 1. status_changed (pending → in_progress)
        # 2. strategy_executed (success)
        assert event_add_mock.call_count == 2

        event_1: ApplicationEvent = event_add_mock.call_args_list[0][0][0]
        assert event_1.event_type == "status_changed"
        assert event_1.event_payload["from"] == "pending"
        assert event_1.event_payload["to"] == "in_progress"

        event_2: ApplicationEvent = event_add_mock.call_args_list[1][0][0]
        assert event_2.event_type == "strategy_executed"
        assert event_2.event_payload["outcome"] == "success"
        assert event_2.event_payload["strategy"] == "portal"

    @pytest.mark.asyncio
    async def test_events_recorded_on_failure(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.email)
        job = make_job()
        resume = make_resume()
        terminal_result = WorkerResult(
            outcome=WorkerOutcome.terminal_failure,
            error_message="SMTP rejected",
        )

        event_add_mock = MagicMock()
        monkeypatch.setattr(
            "src.workers.base.ApplicationRepository.get_by_job_and_strategy",
            AsyncMock(return_value=app),
        )
        monkeypatch.setattr(
            "src.workers.base.JobRepository.get_by_id",
            AsyncMock(return_value=job),
        )
        monkeypatch.setattr(
            "src.workers.base.ResumeRepository.get_tailored_for_job",
            AsyncMock(return_value=None),
        )
        monkeypatch.setattr(
            "src.workers.base.ResumeRepository.get_base_resume",
            AsyncMock(return_value=resume),
        )
        monkeypatch.setattr(
            "src.workers.base.ApplicationEventRepository.add",
            event_add_mock,
            raising=False,
        )

        worker = EmailWorker(
            session=mock_session,
            strategy=MockStrategy(terminal_result),
        )
        await worker.execute(job_id)

        assert event_add_mock.call_count == 2

        event_2: ApplicationEvent = event_add_mock.call_args_list[1][0][0]
        assert event_2.event_type == "strategy_executed"
        assert event_2.event_payload["outcome"] == "terminal_failure"
        assert event_2.event_payload["error"] == "SMTP rejected"


# ---------------------------------------------------------------------------
# Regression Tests
# ---------------------------------------------------------------------------


class TestRegressionTests:
    @pytest.mark.asyncio
    async def test_unexpected_exception_handled(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        """Unexpected exceptions are caught and produce terminal failure."""
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        resume = make_resume()

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=FailingStrategy(RuntimeError("Something broke")),
        )
        result = await worker.execute(job_id)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "Unexpected error" in result.error_message
        assert app.status == ApplicationStatus.permanently_failed

    @pytest.mark.asyncio
    async def test_attempt_count_increments(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.portal)
        job = make_job()
        resume = make_resume()
        success_result = WorkerResult(outcome=WorkerOutcome.success)

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        worker = PortalWorker(
            session=mock_session,
            strategy=MockStrategy(success_result),
        )
        await worker.execute(job_id)

        assert app.attempt_count == 1

    @pytest.mark.asyncio
    async def test_worker_context_carries_all_entities(
        self, mock_session, job_id, make_application, make_job, make_resume, monkeypatch
    ):
        app = make_application(strategy=ApplicationStrategy.form)
        job = make_job()
        resume = make_resume()

        _patch_repos(monkeypatch, application=app, job=job, base_resume=resume)

        captured_context = []

        class CapturingStrategy(BaseStrategy):
            async def execute(self, context: WorkerContext) -> WorkerResult:
                captured_context.append(context)
                return WorkerResult(outcome=WorkerOutcome.success)

        worker = GoogleFormWorker(
            session=mock_session,
            strategy=CapturingStrategy(),
        )
        await worker.execute(job_id)

        assert len(captured_context) == 1
        ctx = captured_context[0]
        assert ctx.application is app
        assert ctx.job is job
        assert ctx.resume is resume
