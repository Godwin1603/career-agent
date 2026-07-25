import logging
import uuid
from typing import Optional

from src.ai.client import AIRetryableError, AIValidationError, GeminiClient
from src.ai.prompts.job_extraction import JobExtractionPromptBuilder
from src.core.enums import JobStatus
from src.core.exceptions import EntityNotFound
from src.jobs.dto import AIEnrichmentResponse
from src.jobs.repository import JobRepository

logger = logging.getLogger(__name__)


from sqlalchemy.ext.asyncio import AsyncSession


class JobEnrichmentService:
    """
    Service responsible for enriching an ingested job using AI.
    """

    def __init__(self, session: AsyncSession, ai_client: GeminiClient):
        self.session = session
        self.job_repo = JobRepository(session)
        self.ai_client = ai_client

    async def enrich_job(self, job_id: uuid.UUID) -> Optional[bool]:
        """
        Enriches a job by calling the AI to extract fields and compute a relevance score.

        Args:
            job_id: The ID of the Job to enrich.

        Returns:
            True if enrichment succeeded, False if a retryable AI error occurred.
            None if the job was not found or has no raw message.
        """
        try:
            job = await self.job_repo.get_by_id(job_id)
        except EntityNotFound:
            logger.warning(f"Job {job_id} not found.")
            return None

        if not job.raw_message:
            logger.warning(f"Job {job_id} has no associated raw message.")
            return None

        prompt = JobExtractionPromptBuilder.build_prompt(job.raw_message.raw_text)

        try:
            # We pass the Pydantic schema to the AI client
            response_dto = await self.ai_client.generate_structured(
                prompt=prompt, schema=AIEnrichmentResponse
            )
        except AIRetryableError as e:
            logger.error(f"Retryable AI error enriching job {job_id}: {e}")
            return False
        except AIValidationError as e:
            logger.error(f"Validation error enriching job {job_id}: {e}")
            # The prompt requires returning a retryable failure for AI failures.
            # So we don't update the status to failed, we return False to trigger a retry.
            return False
        except Exception as e:
            logger.error(f"Unexpected error enriching job {job_id}: {e}")
            return False

        # Map AI results back to the Job model
        job.company_name = response_dto.company_name or job.company_name
        job.role_title = response_dto.role_title or job.role_title
        job.location = response_dto.location or job.location
        job.is_remote = (
            response_dto.is_remote
            if response_dto.is_remote is not None
            else job.is_remote
        )
        job.application_url = response_dto.application_url or job.application_url
        job.email_address = response_dto.email_address or job.email_address
        job.google_form_url = response_dto.google_form_url or job.google_form_url
        job.salary_range = response_dto.salary_range or job.salary_range
        job.detected_portal = response_dto.detected_portal or job.detected_portal

        job.relevance_score = response_dto.relevance_score

        # We assume the job is now successfully processed
        job.status = JobStatus.enriched

        await self.session.commit()
        return True
