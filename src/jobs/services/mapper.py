from src.jobs.dto import AIEnrichmentResponse
from src.jobs.models import Job


class AIEnrichmentMapper:
    """
    Maps AI enrichment DTOs to Job entities.
    """

    @staticmethod
    def map_to_job(job: Job, response_dto: AIEnrichmentResponse) -> Job:
        """
        Updates the job entity with values extracted by the AI.
        Does not commit to the database.

        Args:
            job: The Job entity to update.
            response_dto: The AI enrichment results.

        Returns:
            The updated Job entity.
        """
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

        # TODO: Persist prompt_version when metadata column is added to Job schema.
        # e.g., if not job.metadata: job.metadata = {}
        # job.metadata["prompt_version"] = response_dto.prompt_version

        return job
