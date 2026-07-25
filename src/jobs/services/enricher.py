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
            # Add prompt version if supported
            response_dto.prompt_version = JobExtractionPromptBuilder.get_version()
        except AIRetryableError as e:
            logger.error(
                f"Retryable AI error enriching job {job_id}: {e.__class__.__name__}"
            )
            return False
        except AIValidationError as e:
            logger.error(
                f"Validation error enriching job {job_id}: {e.__class__.__name__}"
            )
            # The prompt requires returning a retryable failure for AI failures.
            # So we don't update the status to failed, we return False to trigger a retry.
            return False
        except Exception as e:
            logger.error(
                f"Unexpected error enriching job {job_id}: {e.__class__.__name__}"
            )
            return False

        # Map AI results back to the Job model
        from src.jobs.services.mapper import AIEnrichmentMapper

        job = AIEnrichmentMapper.map_to_job(job, response_dto)

        # Log AI extraction success (no raw prompt/response/resume text)
        logger.info(
            f"Successfully enriched job {job_id}",
            extra={
                "job_id": str(job_id),
                "model_name": self.ai_client.model_name,
                "prompt_version": response_dto.prompt_version,
                "relevance_score": response_dto.relevance_score,
                "success": True,
            },
        )

        # We assume the job is now successfully processed
        job.status = JobStatus.enriched

        await self.session.commit()
        return True
