"""
Base application worker.

Encapsulates the shared lifecycle for all strategy workers:

    Load payload → Validate → Load entities → Mark in_progress →
    Execute strategy → Persist outcome → Record ApplicationEvent

Concrete workers only need to:
    1. Define their ApplicationStrategy
    2. Provide a BaseStrategy implementation
    3. Optionally override _load_resume() for strategy-specific resume logic
"""

import logging
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.applications.models import Application, ApplicationEvent
from src.applications.repository import (
    ApplicationEventRepository,
    ApplicationRepository,
)
from src.core.enums import ApplicationStatus, ApplicationStrategy
from src.core.exceptions import EntityNotFound
from src.jobs.models import Job
from src.jobs.repository import JobRepository
from src.resumes.models import Resume
from src.resumes.repository import ResumeRepository
from src.workers.dto import WorkerContext, WorkerOutcome, WorkerResult
from src.workers.exceptions import WorkerRetryableError, WorkerTerminalError
from src.workers.strategies import BaseStrategy

logger = logging.getLogger(__name__)


class BaseApplicationWorker(ABC):
    """
    Template-method base class for application workers.

    Subclasses must implement:
        - strategy_type: the ApplicationStrategy this worker handles
        - _get_strategy(): returns the BaseStrategy to execute
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._app_repo = ApplicationRepository(session)
        self._event_repo = ApplicationEventRepository(session)
        self._job_repo = JobRepository(session)
        self._resume_repo = ResumeRepository(session)

    @property
    @abstractmethod
    def strategy_type(self) -> ApplicationStrategy:
        """The strategy this worker handles."""
        ...

    @abstractmethod
    def _get_strategy(self) -> BaseStrategy:
        """Return the concrete strategy implementation."""
        ...

    async def execute(self, job_id: uuid.UUID) -> WorkerResult:
        """
        Main entry point. Orchestrates the full worker lifecycle.

        Args:
            job_id: The UUID of the Job to process.

        Returns:
            WorkerResult with the outcome of the strategy execution.
        """
        application: Optional[Application] = None
        start_time = time.monotonic()

        try:
            # 1. Load entities
            application = await self._load_application(job_id)
            job = await self._load_job(job_id)
            resume = await self._load_resume(job_id)

            # 2. Validate state (pre-execution idempotency check)
            self._validate_application_state(application)

            # 3. Transition to in_progress (atomic with event)
            await self._transition_to_in_progress(application)

            # 4. Re-validate after transition (idempotency guard against
            #    concurrent workers that may have already completed this)
            if application.status != ApplicationStatus.in_progress:
                raise WorkerTerminalError(
                    f"Application {application.id} state changed unexpectedly "
                    f"during transition: {application.status.value}"
                )

            # 5. Build context and execute strategy
            context = WorkerContext(
                application=application,
                job=job,
                resume=resume,
            )
            strategy = self._get_strategy()
            result = await strategy.execute(context)

            # 6. Enrich result metadata with timing and attempt info
            execution_ms = (time.monotonic() - start_time) * 1000
            result.metadata["execution_time_ms"] = round(execution_ms, 2)
            result.metadata["attempt_number"] = application.attempt_count

            # 7. Persist outcome (atomic with event)
            await self._persist_outcome(application, result)

            return result

        except WorkerTerminalError as e:
            logger.error(
                "Terminal worker error",
                extra={
                    "job_id": str(job_id),
                    "strategy": self.strategy_type.value,
                    "error": str(e),
                },
            )
            execution_ms = (time.monotonic() - start_time) * 1000
            result = WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=str(e),
                metadata={
                    "execution_time_ms": round(execution_ms, 2),
                    "attempt_number": (
                        application.attempt_count if application is not None else 0
                    ),
                },
            )
            if application is not None:
                await self._persist_outcome(application, result)
            return result

        except WorkerRetryableError as e:
            logger.warning(
                "Retryable worker error",
                extra={
                    "job_id": str(job_id),
                    "strategy": self.strategy_type.value,
                    "error": str(e),
                },
            )
            execution_ms = (time.monotonic() - start_time) * 1000
            result = WorkerResult(
                outcome=WorkerOutcome.retryable_failure,
                error_message=str(e),
                metadata={
                    "execution_time_ms": round(execution_ms, 2),
                    "attempt_number": (
                        application.attempt_count if application is not None else 0
                    ),
                },
            )
            if application is not None:
                await self._persist_outcome(application, result)
            return result

        except Exception as e:
            logger.error(
                "Unexpected worker error",
                extra={
                    "job_id": str(job_id),
                    "strategy": self.strategy_type.value,
                    "error": e.__class__.__name__,
                },
            )
            execution_ms = (time.monotonic() - start_time) * 1000
            result = WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=f"Unexpected error: {e.__class__.__name__}",
                metadata={
                    "execution_time_ms": round(execution_ms, 2),
                    "attempt_number": (
                        application.attempt_count if application is not None else 0
                    ),
                },
            )
            if application is not None:
                await self._persist_outcome(application, result)
            return result

    async def _load_application(self, job_id: uuid.UUID) -> Application:
        """Load the Application for this job and strategy."""
        application = await self._app_repo.get_by_job_and_strategy(
            job_id, self.strategy_type
        )
        if application is None:
            raise WorkerTerminalError(
                f"Application not found for job={job_id} strategy={self.strategy_type.value}"
            )
        return application

    async def _load_job(self, job_id: uuid.UUID) -> Job:
        """Load the Job entity."""
        try:
            return await self._job_repo.get_by_id(job_id)
        except EntityNotFound:
            raise WorkerTerminalError(f"Job not found: {job_id}")

    async def _load_resume(self, job_id: uuid.UUID) -> Optional[Resume]:
        """
        Explicit resume selection for the job.

        Priority order:
            1. Tailored resume (job-specific)
            2. Base resume (fallback)
            3. None (no resume available — strategy decides how to handle)
        """
        resume = await self._resume_repo.get_tailored_for_job(job_id)
        if resume is not None:
            logger.info(
                "Selected tailored resume",
                extra={
                    "job_id": str(job_id),
                    "resume_id": str(resume.id),
                    "strategy": self.strategy_type.value,
                    "resume_type": "tailored",
                },
            )
            return resume

        resume = await self._resume_repo.get_base_resume()
        if resume is not None:
            logger.info(
                "Falling back to base resume",
                extra={
                    "job_id": str(job_id),
                    "resume_id": str(resume.id),
                    "strategy": self.strategy_type.value,
                    "resume_type": "base",
                },
            )
            return resume

        logger.warning(
            "No resume available",
            extra={
                "job_id": str(job_id),
                "strategy": self.strategy_type.value,
            },
        )
        return None

    def _validate_application_state(self, application: Application) -> None:
        """
        Validate that the application is in a state that allows processing.

        Processable states: pending, failed (retry).
        Non-processable: success, in_progress, permanently_failed, skipped.

        The in_progress check prevents duplicate submissions if a worker
        retries after partial completion.
        """
        if application.status not in (
            ApplicationStatus.pending,
            ApplicationStatus.failed,
        ):
            raise WorkerTerminalError(
                f"Application {application.id} is in non-processable state: "
                f"{application.status.value}"
            )

    async def _transition_to_in_progress(self, application: Application) -> None:
        """
        Mark the application as in_progress and record the event.
        State change and event are flushed together to ensure atomicity
        within the caller's transaction boundary.
        """
        previous_status = application.status.value
        application.status = ApplicationStatus.in_progress
        application.attempt_count += 1

        await self._record_event(
            application,
            event_type="status_changed",
            payload={
                "from": previous_status,
                "to": ApplicationStatus.in_progress.value,
                "attempt": application.attempt_count,
            },
        )
        await self._session.flush()

    async def _persist_outcome(
        self, application: Application, result: WorkerResult
    ) -> None:
        """
        Update the application status based on the WorkerResult
        and record an ApplicationEvent.

        The state update and event recording share a single flush
        to ensure they are persisted atomically within the caller's
        transaction boundary.
        """
        if result.outcome == WorkerOutcome.success:
            application.status = ApplicationStatus.success
            application.applied_at = datetime.now(timezone.utc)
            application.last_error = None
        elif result.outcome == WorkerOutcome.retryable_failure:
            application.status = ApplicationStatus.failed
            application.last_error = result.error_message
        elif result.outcome == WorkerOutcome.terminal_failure:
            application.status = ApplicationStatus.permanently_failed
            application.last_error = result.error_message

        await self._record_event(
            application,
            event_type="strategy_executed",
            payload={
                "outcome": result.outcome.value,
                "strategy": self.strategy_type.value,
                "error": result.error_message,
                **result.metadata,
            },
        )
        await self._session.flush()

    async def _record_event(
        self,
        application: Application,
        event_type: str,
        payload: Optional[dict] = None,
    ) -> None:
        """Append an ApplicationEvent to the audit log."""
        event = ApplicationEvent(
            application_id=application.id,
            event_type=event_type,
            event_payload=payload,
        )
        self._event_repo.add(event)
