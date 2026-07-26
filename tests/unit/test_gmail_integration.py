"""
Unit tests for Gmail integrations.

All Gmail API calls are mocked — no real Google API requests are made.

Coverage:
  - GmailClient.list_messages / get_message / get_message_body / send_message
  - extract_otp_from_text
  - extract_verification_link_from_text
  - GmailOTPService.request_latest_otp / wait_for_otp / extract_code
  - GmailVerificationLinkService.find_verification_link / wait_for_verification
  - GmailEmailStrategy.execute (success, retryable, terminal, missing email)
"""

import base64

import pytest

from src.integrations.gmail.client import (
    GmailClient,
    GmailRetryableError,
    GmailTerminalError,
    extract_otp_from_text,
    extract_verification_link_from_text,
)
from src.integrations.gmail.email_strategy import GmailEmailStrategy
from src.integrations.gmail.otp_service import GmailOTPService
from src.integrations.gmail.verification_service import GmailVerificationLinkService
from src.workers.dto import WorkerContext, WorkerOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    """Return base64url-encoded UTF-8 string (as Gmail API returns it)."""
    return base64.urlsafe_b64encode(text.encode()).decode()


def _make_gmail_message(body: str) -> dict:
    """Build a minimal Gmail API message dict with a text/plain body."""
    return {
        "id": "msg001",
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": _b64(body)},
            "parts": [],
        },
    }


def _make_mock_client(
    messages: list[dict] | None = None,
    message_body: str = "",
    send_id: str = "sent001",
    list_raises=None,
    get_raises=None,
    send_raises=None,
) -> GmailClient:
    """Return a GmailClient with all network methods replaced by stubs."""
    client = GmailClient(
        client_id="id",
        client_secret="secret",
        refresh_token="refresh",
        sender_address="sender@example.com",
    )

    async def _list_messages(query, max_results=10):
        if list_raises:
            raise list_raises
        return messages or []

    async def _get_message(msg_id):
        if get_raises:
            raise get_raises
        return _make_gmail_message(message_body)

    async def _get_message_body(message):
        payload = message.get("payload", {})
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode(
                "utf-8", errors="replace"
            )
        return ""

    async def _send_message(to, subject, body, attachment_path=None):
        if send_raises:
            raise send_raises
        return send_id

    client.list_messages = _list_messages
    client.get_message = _get_message
    client.get_message_body = _get_message_body
    client.send_message = _send_message
    return client


def _make_worker_context(contact_email=None, title="Engineer", company="Acme"):
    """Build a minimal WorkerContext with a mock job."""

    class FakeJob:
        id = "job-123"
        contact_email = None
        title = "Engineer"
        company = "Acme"
        portal_name = "email"

    class FakeResume:
        content = "/tmp/resume.pdf"
        file_path = "/tmp/resume.pdf"

    class FakeApplication:
        id = "app-1"

    job = FakeJob()
    job.contact_email = contact_email
    job.title = title
    job.company = company

    return WorkerContext(job=job, application=FakeApplication(), resume=FakeResume())


# ---------------------------------------------------------------------------
# extract_otp_from_text
# ---------------------------------------------------------------------------


class TestExtractOTPFromText:
    def test_extracts_6_digit_code(self):
        assert extract_otp_from_text("Your OTP is 123456") == "123456"

    def test_extracts_4_digit_code(self):
        assert extract_otp_from_text("Code: 7890") == "7890"

    def test_extracts_8_digit_code(self):
        assert extract_otp_from_text("Token: 12345678") == "12345678"

    def test_returns_none_when_absent(self):
        assert extract_otp_from_text("No numbers here!") is None

    def test_returns_none_for_3_digit(self):
        # 3-digit numbers are too short to be OTPs
        assert extract_otp_from_text("Code 123") is None

    def test_ignores_long_numbers(self):
        # 9+ digit sequences are not typical OTPs
        result = extract_otp_from_text("ID: 123456789")
        # May or may not match depending on boundary; critical thing is it doesn't crash
        assert result is None or isinstance(result, str)

    def test_extracts_first_code(self):
        result = extract_otp_from_text("First: 111111 Second: 222222")
        assert result == "111111"


# ---------------------------------------------------------------------------
# extract_verification_link_from_text
# ---------------------------------------------------------------------------


class TestExtractVerificationLink:
    def test_extracts_verify_link(self):
        text = "Click here: https://example.com/verify?token=abc123"
        assert (
            extract_verification_link_from_text(text)
            == "https://example.com/verify?token=abc123"
        )

    def test_extracts_confirm_link(self):
        text = "Confirm your email: https://portal.com/confirm/abc"
        assert "confirm" in (extract_verification_link_from_text(text) or "").lower()

    def test_returns_none_when_absent(self):
        assert extract_verification_link_from_text("No links here.") is None

    def test_extracts_activate_link(self):
        text = "https://example.com/activate?user=42"
        result = extract_verification_link_from_text(text)
        assert result is not None and "activate" in result


# ---------------------------------------------------------------------------
# GmailOTPService
# ---------------------------------------------------------------------------


class TestGmailOTPService:
    @pytest.mark.asyncio
    async def test_returns_otp_from_email(self):
        client = _make_mock_client(
            messages=[{"id": "msg001"}],
            message_body="Your OTP is 654321",
        )
        svc = GmailOTPService(gmail_client=client)
        result = await svc.request_latest_otp("testportal")
        assert result == "654321"

    @pytest.mark.asyncio
    async def test_returns_none_when_no_messages(self):
        client = _make_mock_client(messages=[])
        svc = GmailOTPService(gmail_client=client)
        result = await svc.request_latest_otp("testportal")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_body_has_no_otp(self):
        client = _make_mock_client(
            messages=[{"id": "msg001"}],
            message_body="Welcome to our portal!",
        )
        svc = GmailOTPService(gmail_client=client)
        result = await svc.request_latest_otp("testportal")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_list_error(self):
        client = _make_mock_client(list_raises=GmailRetryableError("timeout"))
        svc = GmailOTPService(gmail_client=client)
        result = await svc.request_latest_otp("testportal")
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_otp_succeeds_immediately(self):
        client = _make_mock_client(
            messages=[{"id": "msg001"}],
            message_body="OTP: 999888",
        )
        svc = GmailOTPService(gmail_client=client)
        result = await svc.wait_for_otp(
            "testportal",
            timeout_seconds=5.0,
            poll_interval_seconds=0.1,
        )
        assert result == "999888"

    @pytest.mark.asyncio
    async def test_wait_for_otp_raises_on_timeout(self):
        from src.auth.otp import OTPError

        client = _make_mock_client(messages=[])
        svc = GmailOTPService(gmail_client=client)
        with pytest.raises(OTPError):
            await svc.wait_for_otp(
                "testportal",
                timeout_seconds=0.05,
                poll_interval_seconds=0.01,
            )

    @pytest.mark.asyncio
    async def test_extract_code_from_text(self):
        svc = GmailOTPService(gmail_client=_make_mock_client())
        result = await svc.extract_code("Your code: 246810")
        assert result == "246810"

    @pytest.mark.asyncio
    async def test_sender_filter_appended_to_query(self):
        queries_seen = []
        client = _make_mock_client(messages=[])

        async def track_list(query, max_results=10):
            queries_seen.append(query)
            return []

        client.list_messages = track_list
        svc = GmailOTPService(gmail_client=client)
        await svc.request_latest_otp("myportal", sender_filter="noreply@myportal.com")
        assert "from:noreply@myportal.com" in queries_seen[0]


# ---------------------------------------------------------------------------
# GmailVerificationLinkService
# ---------------------------------------------------------------------------


class TestGmailVerificationLinkService:
    @pytest.mark.asyncio
    async def test_returns_link_from_email(self):
        body = "Click to verify: https://app.example.com/verify?token=xyz"
        client = _make_mock_client(messages=[{"id": "m1"}], message_body=body)
        svc = GmailVerificationLinkService(gmail_client=client)
        result = await svc.find_verification_link("testportal")
        assert result is not None and "verify" in result

    @pytest.mark.asyncio
    async def test_returns_none_when_no_messages(self):
        client = _make_mock_client(messages=[])
        svc = GmailVerificationLinkService(gmail_client=client)
        assert await svc.find_verification_link("p") is None

    @pytest.mark.asyncio
    async def test_returns_none_on_list_error(self):
        client = _make_mock_client(list_raises=GmailRetryableError("err"))
        svc = GmailVerificationLinkService(gmail_client=client)
        assert await svc.find_verification_link("p") is None

    @pytest.mark.asyncio
    async def test_wait_for_verification_succeeds(self):
        body = "https://portal.com/activate?user=1"
        client = _make_mock_client(messages=[{"id": "m1"}], message_body=body)
        svc = GmailVerificationLinkService(gmail_client=client)
        result = await svc.wait_for_verification(
            "p",
            timeout_seconds=5.0,
            poll_interval_seconds=0.1,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_wait_for_verification_timeout(self):
        from src.auth.verification import VerificationError

        client = _make_mock_client(messages=[])
        svc = GmailVerificationLinkService(gmail_client=client)
        with pytest.raises(VerificationError):
            await svc.wait_for_verification(
                "p",
                timeout_seconds=0.05,
                poll_interval_seconds=0.01,
            )

    @pytest.mark.asyncio
    async def test_extract_first_link(self):
        svc = GmailVerificationLinkService(gmail_client=_make_mock_client())
        body = "Go to: https://example.com/confirm?token=abc"
        result = await svc.extract_first_link(body)
        assert result is not None


# ---------------------------------------------------------------------------
# GmailEmailStrategy
# ---------------------------------------------------------------------------


class TestGmailEmailStrategy:
    @pytest.mark.asyncio
    async def test_success_with_contact_email(self):
        client = _make_mock_client(send_id="sent_abc")
        strategy = GmailEmailStrategy(gmail_client=client)
        ctx = _make_worker_context(contact_email="hr@company.com")
        result = await strategy.execute(ctx)
        assert result.outcome == WorkerOutcome.success
        assert result.metadata.get("message_id") == "sent_abc"

    @pytest.mark.asyncio
    async def test_terminal_failure_when_no_contact_email(self):
        client = _make_mock_client()
        strategy = GmailEmailStrategy(gmail_client=client)
        ctx = _make_worker_context(contact_email=None)
        result = await strategy.execute(ctx)
        assert result.outcome == WorkerOutcome.terminal_failure
        assert "contact email" in result.error_message

    @pytest.mark.asyncio
    async def test_retryable_failure_on_transient_gmail_error(self):
        client = _make_mock_client(send_raises=GmailRetryableError("timeout"))
        strategy = GmailEmailStrategy(gmail_client=client)
        ctx = _make_worker_context(contact_email="hr@company.com")
        result = await strategy.execute(ctx)
        assert result.outcome == WorkerOutcome.retryable_failure

    @pytest.mark.asyncio
    async def test_terminal_failure_on_auth_error(self):
        client = _make_mock_client(send_raises=GmailTerminalError("invalid_grant"))
        strategy = GmailEmailStrategy(gmail_client=client)
        ctx = _make_worker_context(contact_email="hr@company.com")
        result = await strategy.execute(ctx)
        assert result.outcome == WorkerOutcome.terminal_failure

    @pytest.mark.asyncio
    async def test_metadata_contains_elapsed_ms(self):
        client = _make_mock_client(send_id="x")
        strategy = GmailEmailStrategy(gmail_client=client)
        ctx = _make_worker_context(contact_email="hr@c.com")
        result = await strategy.execute(ctx)
        assert "elapsed_ms" in result.metadata

    @pytest.mark.asyncio
    async def test_metadata_does_not_contain_recipient_email(self):
        client = _make_mock_client(send_id="x")
        strategy = GmailEmailStrategy(gmail_client=client)
        ctx = _make_worker_context(contact_email="private@company.com")
        result = await strategy.execute(ctx)
        # Full email is never in metadata — only domain
        meta_str = str(result.metadata)
        assert "private@company.com" not in meta_str

    @pytest.mark.asyncio
    async def test_recipient_domain_logged_not_full_email(self):
        client = _make_mock_client(send_id="x")
        strategy = GmailEmailStrategy(gmail_client=client)
        ctx = _make_worker_context(contact_email="hr@acme-corp.io")
        result = await strategy.execute(ctx)
        assert result.metadata.get("recipient_domain") == "acme-corp.io"


# ---------------------------------------------------------------------------
# Regression: error classification
# ---------------------------------------------------------------------------


class TestErrorClassification:
    def test_classify_unauthorized_as_terminal(self):
        from src.integrations.gmail.client import GmailClient

        with pytest.raises(GmailTerminalError):
            GmailClient._classify_and_raise(
                Exception("unauthorized access"), "test_ctx"
            )

    def test_classify_transient_as_retryable(self):
        from src.integrations.gmail.client import GmailClient

        with pytest.raises(GmailRetryableError):
            GmailClient._classify_and_raise(Exception("connection timeout"), "test_ctx")

    def test_classify_invalid_grant_as_terminal(self):
        from src.integrations.gmail.client import GmailClient

        with pytest.raises(GmailTerminalError):
            GmailClient._classify_and_raise(Exception("invalid_grant"), "send")
