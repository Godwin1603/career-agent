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

        try:
            # 1. Load entities
            application = await self._load_application(job_id)
            job = await self._load_job(job_id)
            resume = await self._load_resume(job_id)

            # 2. Validate state
            self._validate_application_state(application)

            # 3. Transition to in_progress
            await self._transition_to_in_progress(application)

            # 4. Build context and execute strategy
            context = WorkerContext(
                application=application,
                job=job,
                resume=resume,
            )
            strategy = self._get_strategy()
            result = await strategy.execute(context)

            # 5. Persist outcome
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
            result = WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=str(e),
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
            result = WorkerResult(
                outcome=WorkerOutcome.retryable_failure,
                error_message=str(e),
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
            result = WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=f"Unexpected error: {e.__class__.__name__}",
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
        Load a resume for the job.
        Attempts tailored first, falls back to base.
        Returns None if no resume is available (strategies may choose how to handle).
        """
        resume = await self._resume_repo.get_tailored_for_job(job_id)
        if resume is not None:
            return resume
        return await self._resume_repo.get_base_resume()

    def _validate_application_state(self, application: Application) -> None:
        """
        Validate that the application is in a state that allows processing.
        Only pending applications can be picked up by workers.
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
        """Mark the application as in_progress and record the event."""
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
