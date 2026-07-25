import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import JobStatus, RawMessageStatus
from src.jobs.models import Job, JobRawMessage
from src.jobs.repository import JobRawMessageRepository, JobRepository
from src.jobs.services.normalizer import JobNormalizer
from src.jobs.services.parser import JobParser

logger = logging.getLogger(__name__)


class MessageIngestionService:
    """
    Orchestrates the ingestion of a raw Telegram message into a Job record.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self.raw_repo = JobRawMessageRepository(session)
        self.job_repo = JobRepository(session)

    async def ingest_message(
        self, telegram_message_id: int, channel_id: int, text: str
    ) -> Job | None:
        """
        Deduplicates, parses, normalizes, and persists a Job.
        Returns the created Job, or None if it was a duplicate.
        Raises exceptions on unexpected failures.
        """
        # 1. Deduplication
        if await self.raw_repo.exists_by_telegram_ids(telegram_message_id, channel_id):
            logger.info(
                f"Message {telegram_message_id} from channel {channel_id} already ingested. Skipping."
            )
            return None

        # 2. Persist Raw Message
        raw_msg = JobRawMessage(
            telegram_message_id=telegram_message_id,
            channel_id=channel_id,
            raw_text=text,
            status=RawMessageStatus.pending,
        )
        await self.raw_repo.create(raw_msg)
        await self.session.flush()

        try:
            async with self.session.begin_nested():
                # 3. Parse
                parsed_dto = JobParser.parse(text)

                # 4. Normalize
                normalized_dto = JobNormalizer.normalize(parsed_dto)

                # 5. Job Creation
                job = Job(
                    raw_message_id=raw_msg.id,
                    company_name=normalized_dto.company_name,
                    role_title=normalized_dto.role_title,
                    location=normalized_dto.location,
                    is_remote=normalized_dto.is_remote,
                    application_url=normalized_dto.application_url,
                    email_address=normalized_dto.email_address,
                    google_form_url=normalized_dto.google_form_url,
                    salary_range=normalized_dto.salary_range,
                    detected_portal=normalized_dto.detected_portal,
                    status=JobStatus.pending,
                )
                await self.job_repo.create(job)

            # Update raw message status on success
            raw_msg.status = RawMessageStatus.processed
            return job

        except Exception as e:
            # Savepoint is rolled back automatically. Update raw_msg in the outer transaction.
            raw_msg.status = RawMessageStatus.failed
            logger.error(f"Failed to ingest message {telegram_message_id}: {e}")
            return None
