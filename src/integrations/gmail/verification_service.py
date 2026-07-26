"""
GmailVerificationLinkService — implements VerificationLinkService using Gmail API.

Polls the inbox for activation/confirmation emails and extracts
the first verification URL found in the body.

SECURITY: Verification URLs are NEVER written to log output.
"""

import asyncio
import logging
from typing import Optional

from src.auth.verification import VerificationError, VerificationLinkService
from src.integrations.gmail.client import (
    GmailClient,
    GmailRetryableError,
    extract_verification_link_from_text,
)

logger = logging.getLogger(__name__)

_DEFAULT_VERIFY_QUERY_TEMPLATE = "is:unread subject:({portal}) newer_than:10m"


class GmailVerificationLinkService(VerificationLinkService):
    """
    VerificationLinkService implementation backed by the Gmail API.

    Searches the inbox for recent unread emails from the portal, scans
    the body for a verification URL, and returns it.

    Verification URLs are NEVER written to log output.

    Args:
        gmail_client: Authenticated :class:`GmailClient` instance.
        query_template: Gmail search query template (must contain ``{portal}``).
    """

    def __init__(
        self,
        gmail_client: GmailClient,
        query_template: str = _DEFAULT_VERIFY_QUERY_TEMPLATE,
    ) -> None:
        self._client = gmail_client
        self._query_template = query_template

    async def find_verification_link(
        self,
        portal: str,
        sender_filter: Optional[str] = None,
    ) -> Optional[str]:
        """
        Search the inbox for a verification link email.

        Returns the URL, or ``None`` when none is found yet.
        The returned URL is NEVER logged.
        """
        query = self._build_query(portal, sender_filter)
        try:
            messages = await self._client.list_messages(query=query, max_results=5)
        except GmailRetryableError as exc:
            logger.warning(
                "Verification inbox search failed (portal=%r): %s",
                portal,
                type(exc).__name__,
            )
            return None

        if not messages:
            logger.debug("No verification emails found (portal=%r)", portal)
            return None

        msg_id = messages[0]["id"]
        try:
            message = await self._client.get_message(msg_id)
            body = await self._client.get_message_body(message)
        except GmailRetryableError as exc:
            logger.warning(
                "Verification email fetch failed (portal=%r, id=%r): %s",
                portal,
                msg_id,
                type(exc).__name__,
            )
            return None

        url = extract_verification_link_from_text(body)
        if url:
            logger.info("Verification link found (portal=%r)", portal)
        else:
            logger.debug("No verification link in email body (portal=%r)", portal)

        # url is intentionally not logged
        return url

    async def extract_first_link(self, email_body: str) -> Optional[str]:
        """Extract the first verification URL from *email_body*.
        Body is NEVER logged.
        """
        return extract_verification_link_from_text(email_body)

    async def wait_for_verification(
        self,
        portal: str,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 10.0,
        sender_filter: Optional[str] = None,
    ) -> str:
        """
        Poll until a verification link arrives or *timeout_seconds* elapses.

        Raises:
            VerificationError: when no link is received within the timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            url = await self.find_verification_link(portal, sender_filter)
            if url:
                return url
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval_seconds, remaining))

        raise VerificationError(
            f"Verification link not received within {timeout_seconds}s "
            f"(portal={portal!r})"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_query(self, portal: str, sender_filter: Optional[str]) -> str:
        query = self._query_template.format(portal=portal)
        if sender_filter:
            query += f" from:{sender_filter}"
        return query
