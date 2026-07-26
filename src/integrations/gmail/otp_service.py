"""
GmailOTPService — implements OTPService using the Gmail API.

Polls the inbox for emails matching a portal-specific query, extracts
a numeric OTP code from the body, and returns it to the caller.

SECURITY: OTP codes are NEVER written to logs.
"""

import asyncio
import logging
from typing import Optional

from src.auth.otp import OTPError, OTPService
from src.integrations.gmail.client import (
    GmailClient,
    GmailRetryableError,
    extract_otp_from_text,
)

logger = logging.getLogger(__name__)

# Default query used to locate OTP emails
_DEFAULT_OTP_QUERY_TEMPLATE = "is:unread subject:({portal}) newer_than:5m"


class GmailOTPService(OTPService):
    """
    OTPService implementation backed by the Gmail API.

    Searches the inbox for recent unread emails whose subject contains
    the portal name, parses the first 4–8 digit code found in the body,
    and returns it.

    OTP values are NEVER written to log output.

    Args:
        gmail_client: Authenticated :class:`GmailClient` instance.
        query_template: Gmail search query template.  Must contain
            ``{portal}`` which is substituted at call time.
    """

    def __init__(
        self,
        gmail_client: GmailClient,
        query_template: str = _DEFAULT_OTP_QUERY_TEMPLATE,
    ) -> None:
        self._client = gmail_client
        self._query_template = query_template

    async def request_latest_otp(
        self,
        portal: str,
        sender_filter: Optional[str] = None,
    ) -> Optional[str]:
        """
        Search the inbox for an OTP email and extract the code.

        Returns ``None`` when no matching email is found yet.
        The returned code is NEVER logged.
        """
        query = self._build_query(portal, sender_filter)
        try:
            messages = await self._client.list_messages(query=query, max_results=5)
        except GmailRetryableError as exc:
            logger.warning(
                "OTP inbox search failed (portal=%r): %s", portal, type(exc).__name__
            )
            return None

        if not messages:
            logger.debug("No OTP emails found (portal=%r)", portal)
            return None

        # Inspect the most recent message
        msg_id = messages[0]["id"]
        try:
            message = await self._client.get_message(msg_id)
            body = await self._client.get_message_body(message)
        except GmailRetryableError as exc:
            logger.warning(
                "OTP email fetch failed (portal=%r, id=%r): %s",
                portal,
                msg_id,
                type(exc).__name__,
            )
            return None

        code = extract_otp_from_text(body)
        if code:
            logger.info("OTP extracted (portal=%r)", portal)
        else:
            logger.debug("OTP not found in email body (portal=%r)", portal)

        # code is intentionally not logged
        return code

    async def wait_for_otp(
        self,
        portal: str,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 5.0,
        sender_filter: Optional[str] = None,
    ) -> str:
        """
        Poll until an OTP arrives or *timeout_seconds* elapses.

        Raises:
            OTPError: when no OTP is received within the timeout.
        """
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            code = await self.request_latest_otp(portal, sender_filter)
            if code:
                return code
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            await asyncio.sleep(min(poll_interval_seconds, remaining))

        raise OTPError(
            f"OTP not received within {timeout_seconds}s (portal={portal!r})"
        )

    async def extract_code(self, raw_text: str) -> Optional[str]:
        """Extract a numeric OTP from *raw_text*. Text is NEVER logged."""
        return extract_otp_from_text(raw_text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_query(self, portal: str, sender_filter: Optional[str]) -> str:
        query = self._query_template.format(portal=portal)
        if sender_filter:
            query += f" from:{sender_filter}"
        return query
