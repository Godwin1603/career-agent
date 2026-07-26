"""
GmailEmailStrategy — implements EmailStrategy using the Gmail API.

Sends cold job application emails via the authenticated Gmail account,
optionally attaching a resume PDF.

SECURITY:
- The recipient address is logged only as a domain (e.g. company.com).
- Email body content is NEVER logged.
- Resume attachment path is NEVER logged.
"""

import logging
import time
from typing import Optional

from src.integrations.gmail.client import (
    GmailClient,
    GmailRetryableError,
    GmailTerminalError,
)
from src.workers.dto import WorkerContext, WorkerOutcome, WorkerResult
from src.workers.strategies import BaseStrategy

logger = logging.getLogger(__name__)


def _domain_only(email: str) -> str:
    """Return only the domain part of an email address for safe logging."""
    return email.split("@")[-1] if "@" in email else "<unknown>"


class GmailEmailStrategy(BaseStrategy):
    """
    EmailStrategy concrete implementation using the Gmail API.

    Composes a professional cover-letter email, optionally attaches the
    candidate's resume, and sends it to the job contact address extracted
    from the ``Job`` model.

    Retryable:
        GmailRetryableError — transient Gmail API failure

    Terminal:
        GmailTerminalError — auth failure or invalid configuration
        Missing contact email on job

    Args:
        gmail_client: Authenticated :class:`GmailClient` instance.
        subject_template: Email subject.  ``{job_title}`` and
            ``{company}`` are substituted at runtime.
        body_template: Plain-text body.  ``{first_name}``, ``{job_title}``,
            and ``{company}`` are substituted at runtime.
    """

    _DEFAULT_SUBJECT = "Application for {job_title} — {company}"
    _DEFAULT_BODY = (
        "Dear Hiring Team,\n\n"
        "I am writing to express my strong interest in the "
        "{job_title} position at {company}.\n"
        "Please find my resume attached.\n\n"
        "I would welcome the opportunity to discuss how my "
        "experience aligns with your needs.\n\n"
        "Best regards,\n"
        "{first_name}"
    )

    def __init__(
        self,
        gmail_client: GmailClient,
        subject_template: Optional[str] = None,
        body_template: Optional[str] = None,
    ) -> None:
        self._client = gmail_client
        self._subject_tpl = subject_template or self._DEFAULT_SUBJECT
        self._body_tpl = body_template or self._DEFAULT_BODY

    async def execute(self, context: WorkerContext) -> WorkerResult:
        start = time.monotonic()

        job = context.job
        resume = context.resume

        # Resolve contact email from job (field name may vary — use getattr)
        contact_email: Optional[str] = getattr(job, "contact_email", None) or getattr(
            job, "email", None
        )
        if not contact_email:
            return WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message="no contact email on job — email strategy cannot proceed",
            )

        job_title: str = getattr(job, "title", "the advertised position")
        company: str = getattr(job, "company", "your company")
        first_name: str = (
            "Candidate"  # will be enriched once candidate profile is added
        )

        subject = self._subject_tpl.format(job_title=job_title, company=company)
        body = self._body_tpl.format(
            first_name=first_name, job_title=job_title, company=company
        )

        # Resume attachment (path or None)
        attachment_path: Optional[str] = (
            getattr(resume, "file_path", None) if resume else None
        )

        domain = _domain_only(contact_email)
        logger.info(
            "Sending application email (domain=%r, job_title=%r)", domain, job_title
        )

        try:
            msg_id = await self._client.send_message(
                to=contact_email,
                subject=subject,
                body=body,
                attachment_path=attachment_path,
            )
        except GmailRetryableError as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return WorkerResult(
                outcome=WorkerOutcome.retryable_failure,
                error_message=f"Gmail transient error: {type(exc).__name__}",
                metadata={"elapsed_ms": elapsed},
            )
        except GmailTerminalError as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=f"Gmail auth/config error: {type(exc).__name__}",
                metadata={"elapsed_ms": elapsed},
            )

        elapsed = int((time.monotonic() - start) * 1000)
        logger.info(
            "Application email sent (message_id=%r, domain=%r, elapsed_ms=%d)",
            msg_id,
            domain,
            elapsed,
        )
        return WorkerResult(
            outcome=WorkerOutcome.success,
            metadata={
                "message_id": msg_id,
                "recipient_domain": domain,
                "elapsed_ms": elapsed,
            },
        )
