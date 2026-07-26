"""
OTPService interface and mock implementation.

The OTPService interface decouples the authentication layer from the
concrete email provider (Gmail API) that will be implemented in a
future phase.

CRITICAL LOGGING RULE: OTP codes MUST NEVER appear in log output.
Only metadata (portal, profile_id, outcome) may be logged.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class OTPError(Exception):
    """Raised when an OTP operation fails."""


class OTPService(ABC):
    """
    Abstract interface for One-Time Password retrieval.

    Implementations must source OTPs from an email inbox (e.g. Gmail)
    or another delivery channel.  The Gmail API implementation is
    deferred to a future phase.
    """

    @abstractmethod
    async def request_latest_otp(
        self,
        portal: str,
        sender_filter: Optional[str] = None,
    ) -> Optional[str]:
        """
        Attempt to retrieve the most recently delivered OTP.

        Args:
            portal: Portal identifier used to scope the inbox search.
            sender_filter: Optional sender address to narrow results.

        Returns:
            The OTP string, or ``None`` when none is available yet.

        IMPORTANT: Do NOT log the return value.
        """
        ...

    @abstractmethod
    async def wait_for_otp(
        self,
        portal: str,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 5.0,
        sender_filter: Optional[str] = None,
    ) -> str:
        """
        Poll until an OTP arrives or *timeout_seconds* elapses.

        Args:
            portal: Portal identifier used to scope the inbox search.
            timeout_seconds: Maximum wait time.
            poll_interval_seconds: Interval between polling attempts.
            sender_filter: Optional sender address to narrow results.

        Returns:
            The OTP string.

        Raises:
            OTPError: when no OTP is received within the timeout.

        IMPORTANT: Do NOT log the return value.
        """
        ...

    @abstractmethod
    async def extract_code(self, raw_text: str) -> Optional[str]:
        """
        Extract a numeric/alphanumeric OTP code from *raw_text*.

        Args:
            raw_text: Email body or SMS text containing the OTP.

        Returns:
            The extracted code, or ``None`` when not found.

        IMPORTANT: Do NOT log *raw_text* or the return value.
        """
        ...


class MockOTPService(OTPService):
    """
    Mock OTP service for unit testing and local development.

    Returns a configurable fixed code without any email lookup.
    """

    def __init__(self, fixed_otp: str = "123456") -> None:
        self._fixed_otp = fixed_otp
        # Track calls for assertion in tests (code is never logged)
        self._request_calls: list[dict] = []
        self._wait_calls: list[dict] = []

    async def request_latest_otp(
        self,
        portal: str,
        sender_filter: Optional[str] = None,
    ) -> Optional[str]:
        self._request_calls.append({"portal": portal})
        logger.debug("MockOTPService.request_latest_otp called (portal=%r)", portal)
        # Return the fixed code without logging it
        return self._fixed_otp

    async def wait_for_otp(
        self,
        portal: str,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 5.0,
        sender_filter: Optional[str] = None,
    ) -> str:
        self._wait_calls.append({"portal": portal})
        logger.debug("MockOTPService.wait_for_otp called (portal=%r)", portal)
        # Simulate minimal async work without a real network call
        await asyncio.sleep(0)
        return self._fixed_otp

    async def extract_code(self, raw_text: str) -> Optional[str]:
        # In mock mode we just return the fixed OTP; raw_text is not logged
        return self._fixed_otp

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    @property
    def request_call_count(self) -> int:
        return len(self._request_calls)

    @property
    def wait_call_count(self) -> int:
        return len(self._wait_calls)
