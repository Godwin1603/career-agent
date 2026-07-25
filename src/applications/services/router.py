from src.applications.dto import RoutingResult
from src.core.config import settings
from src.core.enums import ApplicationStrategy, JobStatus
from src.jobs.models import Job


class ApplicationRouter:
    """
    Deterministic routing engine for enriched Jobs.
    Evaluates Job attributes and determines which ApplicationStrategies to pursue.
    """

    def route(self, job: Job) -> RoutingResult:
        """
        Evaluate the Job and return a RoutingResult.
        Modifies the Job status to 'skipped' if relevance is too low.
        """
        # Rule 1: Relevance Check
        if (
            job.relevance_score is not None
            and job.relevance_score < settings.RELEVANCE_THRESHOLD
        ):
            job.status = JobStatus.skipped
            return RoutingResult(skipped=True)

        strategies = []

        # Rule 2: Portal URL exists
        if job.application_url or job.detected_portal:
            strategies.append(ApplicationStrategy.portal)

        # Rule 3: Google Form URL exists
        if job.google_form_url:
            strategies.append(ApplicationStrategy.form)

        # Rule 4: Email exists
        if job.email_address:
            strategies.append(ApplicationStrategy.email)

        return RoutingResult(strategies=strategies, skipped=False)
