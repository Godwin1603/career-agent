"""
VerificationLinkService interface and mock implementation.

Provides email-based verification link detection for portals that send
"click to confirm" emails instead of OTP codes.

The Gmail API implementation is deferred to a future phase.

CRITICAL LOGGING RULE: Verification links MUST NEVER appear in logs.
Only metadata (portal, profile_id, outcome) may be logged.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """Raised when a verification link operation fails."""


class VerificationLinkService(ABC):
    """
    Abstract interface for email verification link discovery.

    Used when a portal sends a "click to verify" email rather than an OTP.
    """

    @abstractmethod
    async def find_verification_link(
        self,
        portal: str,
        sender_filter: Optional[str] = None,
    ) -> Optional[str]:
        """
        Scan the inbox for a verification link from *portal*.

        Args:
            portal: Portal identifier used to scope the inbox search.
            sender_filter: Optional sender address to narrow results.

        Returns:
            The verification URL as a string, or ``None`` when not found.

        IMPORTANT: Do NOT log the return value.
        """
        ...

    @abstractmethod
    async def extract_first_link(self, email_body: str) -> Optional[str]:
        """
        Extract the first plausible verification URL from *email_body*.

        Args:
            email_body: Raw email text or HTML body.

        Returns:
            The first URL found, or ``None``.

        IMPORTANT: Do NOT log *email_body* or the return value.
        """
        ...

    @abstractmethod
    async def wait_for_verification(
        self,
        portal: str,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 10.0,
        sender_filter: Optional[str] = None,
    ) -> str:
        """
        Poll until a verification link arrives or *timeout_seconds* elapses.

        Args:
            portal: Portal identifier.
            timeout_seconds: Maximum wait time.
            poll_interval_seconds: Interval between polling attempts.
            sender_filter: Optional sender address filter.

        Returns:
            The verification URL.

        Raises:
            VerificationError: when no link is received within the timeout.

        IMPORTANT: Do NOT log the return value.
        """
        ...


class MockVerificationLinkService(VerificationLinkService):
    """
    Mock verification link service for unit testing and local development.

    Returns a configurable fixed URL without any email lookup.
    """

    def __init__(
        self, fixed_url: str = "https://example.com/verify?token=mock"
    ) -> None:
        self._fixed_url = fixed_url
        # Track calls for assertion in tests (URL is never logged)
        self._find_calls: list[dict] = []
        self._wait_calls: list[dict] = []

    async def find_verification_link(
        self,
        portal: str,
        sender_filter: Optional[str] = None,
    ) -> Optional[str]:
        self._find_calls.append({"portal": portal})
        logger.debug(
            "MockVerificationLinkService.find_verification_link called (portal=%r)",
            portal,
        )
        return self._fixed_url

    async def extract_first_link(self, email_body: str) -> Optional[str]:
        # email_body is not logged
        return self._fixed_url

    async def wait_for_verification(
        self,
        portal: str,
        timeout_seconds: float = 120.0,
        poll_interval_seconds: float = 10.0,
        sender_filter: Optional[str] = None,
    ) -> str:
        self._wait_calls.append({"portal": portal})
        logger.debug(
            "MockVerificationLinkService.wait_for_verification called (portal=%r)",
            portal,
        )
        await asyncio.sleep(0)
        return self._fixed_url

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @property
    def find_call_count(self) -> int:
        return len(self._find_calls)

    @property
    def wait_call_count(self) -> int:
        return len(self._wait_calls)
