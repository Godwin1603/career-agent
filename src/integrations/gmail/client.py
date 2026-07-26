"""
GmailClient — async wrapper over the Gmail REST API.

This client runs all blocking googleapiclient calls in a thread pool
executor so the event loop is never blocked.

SECURITY
--------
- OAuth tokens are NEVER logged.
- Email bodies are NEVER logged.
- Only message IDs and metadata counts are surfaced in logs.

Authentication uses the three OAuth fields already present in
``src.core.config.Settings``:
  GMAIL_OAUTH_CLIENT_ID
  GMAIL_OAUTH_CLIENT_SECRET
  GMAIL_OAUTH_REFRESH_TOKEN
"""

import asyncio
import base64
import logging
import re
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Scopes required for reading and sending mail
_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


class GmailClientError(Exception):
    """Base exception for GmailClient errors."""


class GmailRetryableError(GmailClientError):
    """Transient Gmail API error — caller should retry."""


class GmailTerminalError(GmailClientError):
    """Permanent Gmail configuration or auth error."""


class GmailClient:
    """
    Async Gmail API client.

    Builds a Gmail service from OAuth refresh-token credentials and wraps
    every blocking call in ``loop.run_in_executor`` so the async event loop
    is never blocked.

    Args:
        client_id: OAuth2 client ID (from GCP credentials).
        client_secret: OAuth2 client secret.
        refresh_token: Long-lived OAuth2 refresh token.
        sender_address: The Gmail address used for sending.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        sender_address: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._sender_address = sender_address
        self._service = None  # lazy-built on first call

    # ------------------------------------------------------------------
    # Service construction (lazy, thread-safe for single-process use)
    # ------------------------------------------------------------------

    def _build_service(self):
        """Build the Gmail service synchronously (runs in executor)."""
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GmailTerminalError(
                "google-api-python-client or google-auth is not installed. "
                "Install: pip install google-api-python-client google-auth"
            ) from exc

        # Credentials are NOT logged
        creds = Credentials(
            token=None,
            refresh_token=self._refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=self._client_id,
            client_secret=self._client_secret,
            scopes=_GMAIL_SCOPES,
        )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    async def _get_service(self):
        if self._service is None:
            loop = asyncio.get_running_loop()
            self._service = await loop.run_in_executor(None, self._build_service)
        return self._service

    # ------------------------------------------------------------------
    # Internal thread-pool runner
    # ------------------------------------------------------------------

    async def _run(self, func, *args, **kwargs):
        """Execute *func* in the default thread-pool executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_messages(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """
        List messages matching *query*.

        Args:
            query: Gmail search query (e.g. ``'is:unread subject:OTP'``).
            max_results: Maximum number of message stubs to return.

        Returns:
            List of message stub dicts with ``id`` and ``threadId``.
        """
        svc = await self._get_service()
        try:
            result = await self._run(
                svc.users()
                .messages()
                .list(userId="me", q=query, maxResults=max_results)
                .execute
            )
            messages = result.get("messages", [])
            logger.debug("Gmail list_messages returned %d results", len(messages))
            return messages
        except Exception as exc:
            self._classify_and_raise(exc, context="list_messages")

    async def get_message(self, message_id: str) -> dict:
        """
        Fetch a full message by *message_id*.

        Returns the raw Gmail API message dict.
        The body content is NEVER logged.
        """
        svc = await self._get_service()
        try:
            msg = await self._run(
                svc.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute
            )
            logger.debug("Gmail get_message retrieved (id=%r)", message_id)
            return msg
        except Exception as exc:
            self._classify_and_raise(exc, context="get_message")

    async def get_message_body(self, message: dict) -> str:
        """
        Extract the plain-text body from a Gmail message dict.

        Returns empty string when no text/plain part is found.
        The returned body is NEVER logged by this method.
        """
        payload = message.get("payload", {})
        # Single-part message
        if "body" in payload:
            data = payload["body"].get("data", "")
            if data:
                return base64.urlsafe_b64decode(data + "==").decode(
                    "utf-8", errors="replace"
                )
        # Multi-part: walk parts
        for part in payload.get("parts", []):
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    return base64.urlsafe_b64decode(data + "==").decode(
                        "utf-8", errors="replace"
                    )
        return ""

    async def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        attachment_path: Optional[str] = None,
    ) -> str:
        """
        Send an email from the configured sender address.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            body: Plain-text body.
            attachment_path: Optional path to a file to attach (e.g. resume PDF).

        Returns:
            The sent message ID.

        SECURITY: *body*, *to*, and *attachment_path* are NEVER logged.
        """
        svc = await self._get_service()
        raw = self._build_raw_message(to, subject, body, attachment_path)
        try:
            result = await self._run(
                svc.users().messages().send(userId="me", body={"raw": raw}).execute
            )
            msg_id = result.get("id", "")
            logger.info("Email sent (message_id=%r)", msg_id)
            return msg_id
        except Exception as exc:
            self._classify_and_raise(exc, context="send_message")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_raw_message(
        self,
        to: str,
        subject: str,
        body: str,
        attachment_path: Optional[str],
    ) -> str:
        """Build a base64url-encoded RFC 2822 message."""
        if attachment_path:
            msg = MIMEMultipart()
            msg.attach(MIMEText(body, "plain"))
            path = Path(attachment_path)
            with path.open("rb") as fh:
                part = MIMEApplication(fh.read(), Name=path.name)
            part["Content-Disposition"] = f'attachment; filename="{path.name}"'
            msg.attach(part)
        else:
            msg = MIMEText(body, "plain")

        msg["to"] = to
        msg["from"] = self._sender_address
        msg["subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        return raw

    @staticmethod
    def _classify_and_raise(exc: Exception, context: str) -> None:
        """Map Gmail API exceptions to retryable / terminal errors."""
        exc_str = str(exc).lower()
        exc_name = type(exc).__name__
        # Auth/config errors are terminal
        if any(k in exc_str for k in ("unauthorized", "forbidden", "invalid_grant")):
            raise GmailTerminalError(
                f"Gmail auth error in {context}: {exc_name}"
            ) from exc
        # Quota / transient errors are retryable
        raise GmailRetryableError(
            f"Gmail transient error in {context}: {exc_name}"
        ) from exc


# ---------------------------------------------------------------------------
# Utility: OTP extraction
# ---------------------------------------------------------------------------

# Matches common OTP formats: 4–8 digit sequences
_OTP_PATTERN = re.compile(r"\b([0-9]{4,8})\b")

# Common verification URL patterns
_LINK_PATTERN = re.compile(
    r"https?://[^\s\"'<>]+(?:verify|confirm|activate|token|auth)[^\s\"'<>]*",
    re.IGNORECASE,
)


def extract_otp_from_text(text: str) -> Optional[str]:
    """
    Extract the first numeric OTP (4–8 digits) from *text*.

    Returns ``None`` when no match is found.
    *text* is NEVER logged.
    """
    match = _OTP_PATTERN.search(text)
    return match.group(1) if match else None


def extract_verification_link_from_text(text: str) -> Optional[str]:
    """
    Extract the first verification/confirmation URL from *text*.

    Returns ``None`` when no match is found.
    *text* and the returned URL are NEVER logged.
    """
    match = _LINK_PATTERN.search(text)
    return match.group(0) if match else None
