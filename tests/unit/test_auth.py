"""
Unit tests for Phase 9: Authentication & Identity Services.

Coverage:
  - IdentityContext / AuthenticationResult DTOs
  - AuthenticationState enum
  - MockSecretProvider
  - CredentialProvider (success, missing credentials, retryable error)
  - SessionManager (load, save, validate, invalidate)
  - MockOTPService
  - MockVerificationLinkService
  - AuthenticationOrchestrator (full flow, all failure paths, regression)
"""

import pytest

from src.auth.credentials import (
    CredentialProvider,
    CredentialProviderError,
    MissingCredentialsError,
    PortalCredential,
)
from src.auth.dto import AuthenticationResult, AuthenticationState, IdentityContext
from src.auth.orchestrator import AuthenticationOrchestrator
from src.auth.otp import MockOTPService
from src.auth.secrets import (
    MockSecretProvider,
    SecretNotFoundError,
    SecretProviderError,
)
from src.auth.session import SessionManager
from src.auth.verification import MockVerificationLinkService

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_identity(
    portal: str = "testportal",
    profile_id: str = "testportal_profile",
    username: str = "user@example.com",
) -> IdentityContext:
    return IdentityContext(portal=portal, profile_id=profile_id, username=username)


def _make_secret_provider(portal: str = "testportal") -> MockSecretProvider:
    return MockSecretProvider(
        {
            f"{portal}_username": "user@example.com",
            f"{portal}_password": "s3cr3t",
        }
    )


@pytest.fixture
def tmp_profiles(tmp_path):
    """Return a temporary directory for browser profiles."""
    return str(tmp_path / "profiles")


@pytest.fixture
def session_manager(tmp_profiles):
    return SessionManager(profiles_dir=tmp_profiles)


@pytest.fixture
def credential_provider():
    return CredentialProvider(secret_provider=_make_secret_provider())


@pytest.fixture
def orchestrator(credential_provider, session_manager):
    return AuthenticationOrchestrator(
        credential_provider=credential_provider,
        session_manager=session_manager,
    )


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class TestIdentityContext:
    def test_valid_construction(self):
        ctx = IdentityContext(
            portal="workday", profile_id="workday_alice", username="alice@example.com"
        )
        assert ctx.portal == "workday"
        assert ctx.profile_id == "workday_alice"
        assert ctx.username == "alice@example.com"

    def test_immutable(self):
        ctx = _make_identity()
        with pytest.raises(Exception):  # ValidationError or FrozenInstanceError
            ctx.portal = "other"

    def test_repr_does_not_contain_username(self):
        ctx = _make_identity(username="secret@example.com")
        # repr should not expose username (only portal and profile_id)
        assert "secret@example.com" not in repr(ctx)


class TestAuthenticationResult:
    def test_success_result(self):
        result = AuthenticationResult(success=True, session_loaded=True)
        assert result.success is True
        assert result.session_loaded is True
        assert result.failure_reason is None

    def test_failure_result(self):
        result = AuthenticationResult(success=False, failure_reason="no creds")
        assert result.success is False
        assert result.failure_reason == "no creds"

    def test_immutable(self):
        result = AuthenticationResult(success=True)
        with pytest.raises(Exception):
            result.success = False

    def test_default_metadata_is_dict(self):
        result = AuthenticationResult(success=True)
        assert isinstance(result.metadata, dict)


class TestAuthenticationState:
    def test_all_states_present(self):
        expected = {
            "session_loaded",
            "requires_login",
            "authenticated",
            "missing_credentials",
            "invalid_session",
            "unsupported_portal",
            "retryable_failure",
        }
        actual = {s.value for s in AuthenticationState}
        assert expected == actual


# ---------------------------------------------------------------------------
# SecretProvider
# ---------------------------------------------------------------------------


class TestMockSecretProvider:
    @pytest.mark.asyncio
    async def test_get_existing_secret(self):
        p = MockSecretProvider({"key": "value"})
        assert await p.get_secret("key") == "value"

    @pytest.mark.asyncio
    async def test_missing_secret_raises(self):
        p = MockSecretProvider({})
        with pytest.raises(SecretNotFoundError):
            await p.get_secret("nonexistent")

    @pytest.mark.asyncio
    async def test_set_and_retrieve(self):
        p = MockSecretProvider()
        p.set_secret("dynamic", "hello")
        assert await p.get_secret("dynamic") == "hello"

    @pytest.mark.asyncio
    async def test_remove_then_missing(self):
        p = MockSecretProvider({"k": "v"})
        p.remove_secret("k")
        with pytest.raises(SecretNotFoundError):
            await p.get_secret("k")


# ---------------------------------------------------------------------------
# CredentialProvider
# ---------------------------------------------------------------------------


class TestCredentialProvider:
    @pytest.mark.asyncio
    async def test_load_credentials_success(self):
        provider = CredentialProvider(secret_provider=_make_secret_provider("myportal"))
        cred = await provider.get_credentials("myportal")
        assert isinstance(cred, PortalCredential)
        assert cred.portal == "myportal"
        assert cred.username == "user@example.com"
        assert cred.get_password() == "s3cr3t"

    @pytest.mark.asyncio
    async def test_missing_username_raises_terminal(self):
        secrets = MockSecretProvider({"myportal_password": "s3cr3t"})
        provider = CredentialProvider(secret_provider=secrets)
        with pytest.raises(MissingCredentialsError):
            await provider.get_credentials("myportal")

    @pytest.mark.asyncio
    async def test_missing_password_raises_terminal(self):
        secrets = MockSecretProvider({"myportal_username": "user@example.com"})
        provider = CredentialProvider(secret_provider=secrets)
        with pytest.raises(MissingCredentialsError):
            await provider.get_credentials("myportal")

    @pytest.mark.asyncio
    async def test_empty_portal_raises(self):
        provider = CredentialProvider(secret_provider=MockSecretProvider())
        with pytest.raises(MissingCredentialsError):
            await provider.get_credentials("")

    @pytest.mark.asyncio
    async def test_retryable_secret_provider_error(self):
        """SecretProviderError is re-raised as CredentialProviderError."""
        from unittest.mock import AsyncMock

        secrets = MockSecretProvider()
        secrets.get_secret = AsyncMock(side_effect=SecretProviderError("timeout"))
        provider = CredentialProvider(secret_provider=secrets)
        with pytest.raises(CredentialProviderError):
            await provider.get_credentials("myportal")

    def test_credential_repr_masks_password(self):
        cred = PortalCredential(portal="p", username="u", _password="secret123")
        assert "secret123" not in repr(cred)

    @pytest.mark.asyncio
    async def test_custom_key_names(self):
        secrets = MockSecretProvider({"custom_user": "alice", "custom_pass": "pw"})
        provider = CredentialProvider(secret_provider=secrets)
        cred = await provider.get_credentials(
            "any", username_key="custom_user", password_key="custom_pass"
        )
        assert cred.username == "alice"
        assert cred.get_password() == "pw"


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class TestSessionManager:
    @pytest.mark.asyncio
    async def test_save_and_load_session(self, session_manager):
        await session_manager.save_session("profile1", portal="workday")
        data = await session_manager.load_session("profile1")
        assert data is not None
        assert data["profile_id"] == "profile1"
        assert data["portal"] == "workday"

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, session_manager):
        result = await session_manager.load_session("does_not_exist")
        assert result is None

    @pytest.mark.asyncio
    async def test_validate_after_save(self, session_manager):
        await session_manager.save_session("profile2")
        valid = await session_manager.validate_session("profile2")
        assert valid is True

    @pytest.mark.asyncio
    async def test_validate_missing_profile(self, session_manager):
        valid = await session_manager.validate_session("ghost_profile")
        assert valid is False

    @pytest.mark.asyncio
    async def test_invalidate_removes_session(self, session_manager):
        await session_manager.save_session("profile3")
        assert await session_manager.validate_session("profile3") is True

        await session_manager.invalidate_session("profile3")
        assert await session_manager.validate_session("profile3") is False

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_is_safe(self, session_manager):
        # Should not raise
        await session_manager.invalidate_session("phantom")

    @pytest.mark.asyncio
    async def test_save_with_metadata(self, session_manager):
        await session_manager.save_session(
            "profile4", portal="lever", metadata={"attempt": 1}
        )
        data = await session_manager.load_session("profile4")
        assert data["attempt"] == 1

    @pytest.mark.asyncio
    async def test_load_corrupt_session_returns_none(
        self, session_manager, tmp_profiles
    ):
        import os

        # Write garbage to the session file
        profile_dir = os.path.join(tmp_profiles, "corrupt")
        os.makedirs(profile_dir, exist_ok=True)
        with open(os.path.join(profile_dir, "session.json"), "w") as f:
            f.write("not valid json {{{")

        result = await session_manager.load_session("corrupt")
        assert result is None


# ---------------------------------------------------------------------------
# MockOTPService
# ---------------------------------------------------------------------------


class TestMockOTPService:
    @pytest.mark.asyncio
    async def test_request_latest_otp_returns_fixed_code(self):
        svc = MockOTPService(fixed_otp="987654")
        code = await svc.request_latest_otp("myportal")
        assert code == "987654"

    @pytest.mark.asyncio
    async def test_wait_for_otp_returns_fixed_code(self):
        svc = MockOTPService(fixed_otp="111111")
        code = await svc.wait_for_otp("myportal", timeout_seconds=5)
        assert code == "111111"

    @pytest.mark.asyncio
    async def test_extract_code(self):
        svc = MockOTPService(fixed_otp="555555")
        code = await svc.extract_code("Your code is 555555")
        assert code == "555555"

    def test_call_counts(self):
        svc = MockOTPService()
        assert svc.request_call_count == 0
        assert svc.wait_call_count == 0

    @pytest.mark.asyncio
    async def test_call_counts_increment(self):
        svc = MockOTPService()
        await svc.request_latest_otp("p")
        await svc.wait_for_otp("p")
        assert svc.request_call_count == 1
        assert svc.wait_call_count == 1


# ---------------------------------------------------------------------------
# MockVerificationLinkService
# ---------------------------------------------------------------------------


class TestMockVerificationLinkService:
    @pytest.mark.asyncio
    async def test_find_returns_fixed_url(self):
        svc = MockVerificationLinkService(fixed_url="https://example.com/verify")
        url = await svc.find_verification_link("myportal")
        assert url == "https://example.com/verify"

    @pytest.mark.asyncio
    async def test_extract_first_link(self):
        svc = MockVerificationLinkService(fixed_url="https://example.com/verify")
        url = await svc.extract_first_link("Click here: https://example.com/verify")
        assert url == "https://example.com/verify"

    @pytest.mark.asyncio
    async def test_wait_for_verification(self):
        svc = MockVerificationLinkService()
        url = await svc.wait_for_verification("myportal")
        assert url.startswith("https://")

    def test_call_counts(self):
        svc = MockVerificationLinkService()
        assert svc.find_call_count == 0
        assert svc.wait_call_count == 0

    @pytest.mark.asyncio
    async def test_call_counts_increment(self):
        svc = MockVerificationLinkService()
        await svc.find_verification_link("p")
        await svc.wait_for_verification("p")
        assert svc.find_call_count == 1
        assert svc.wait_call_count == 1


# ---------------------------------------------------------------------------
# AuthenticationOrchestrator
# ---------------------------------------------------------------------------


class TestAuthenticationOrchestrator:
    @pytest.mark.asyncio
    async def test_session_loaded_when_valid(self, orchestrator, session_manager):
        identity = _make_identity()
        # Pre-create a valid session
        await session_manager.save_session(identity.profile_id, portal=identity.portal)

        result = await orchestrator.authenticate(identity)

        assert result.success is True
        assert result.session_loaded is True
        assert result.requires_login is False
        assert result.metadata["state"] == AuthenticationState.session_loaded

    @pytest.mark.asyncio
    async def test_requires_login_when_no_session(self, orchestrator):
        identity = _make_identity()
        # No session saved — should ask caller to log in
        result = await orchestrator.authenticate(identity)

        assert result.success is True
        assert result.requires_login is True
        assert result.session_loaded is False
        assert result.metadata["state"] == AuthenticationState.requires_login

    @pytest.mark.asyncio
    async def test_missing_credentials_returns_terminal_failure(self, session_manager):
        # Provider has no secrets at all
        provider = CredentialProvider(secret_provider=MockSecretProvider({}))
        orch = AuthenticationOrchestrator(
            credential_provider=provider, session_manager=session_manager
        )
        result = await orch.authenticate(_make_identity())

        assert result.success is False
        assert result.metadata["state"] == AuthenticationState.missing_credentials

    @pytest.mark.asyncio
    async def test_retryable_credential_error(self, session_manager):
        from unittest.mock import AsyncMock

        provider = CredentialProvider(secret_provider=MockSecretProvider())
        provider.get_credentials = AsyncMock(
            side_effect=CredentialProviderError("timeout")
        )
        orch = AuthenticationOrchestrator(
            credential_provider=provider, session_manager=session_manager
        )
        result = await orch.authenticate(_make_identity())

        assert result.success is False
        assert result.metadata["state"] == AuthenticationState.retryable_failure

    @pytest.mark.asyncio
    async def test_invalid_identity_empty_portal(self, orchestrator):
        identity = IdentityContext(portal="", profile_id="pid", username="u")
        result = await orchestrator.authenticate(identity)

        assert result.success is False
        assert "invalid identity context" in result.failure_reason

    @pytest.mark.asyncio
    async def test_invalid_identity_empty_profile_id(self, orchestrator):
        identity = IdentityContext(portal="workday", profile_id="", username="u")
        result = await orchestrator.authenticate(identity)

        assert result.success is False
        assert "invalid identity context" in result.failure_reason

    @pytest.mark.asyncio
    async def test_session_invalidated_triggers_login(
        self, orchestrator, session_manager
    ):
        identity = _make_identity()
        await session_manager.save_session(identity.profile_id, portal=identity.portal)
        await session_manager.invalidate_session(identity.profile_id)

        result = await orchestrator.authenticate(identity)

        assert result.success is True
        assert result.requires_login is True

    @pytest.mark.asyncio
    async def test_metadata_includes_profile_and_portal(self, session_manager):
        # Use a provider that has lever credentials
        secrets = MockSecretProvider(
            {
                "lever_username": "alice@example.com",
                "lever_password": "s3cr3t",
            }
        )
        orch = AuthenticationOrchestrator(
            credential_provider=CredentialProvider(secret_provider=secrets),
            session_manager=session_manager,
        )
        identity = _make_identity(portal="lever", profile_id="lever_p1")
        result = await orch.authenticate(identity)

        assert result.metadata.get("portal") == "lever"
        assert result.metadata.get("profile_id") == "lever_p1"


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------


class TestRegressionTests:
    @pytest.mark.asyncio
    async def test_multiple_portals_isolated(self, session_manager):
        """Sessions for different portals must not interfere."""
        await session_manager.save_session("portal_a_profile", portal="portal_a")
        # portal_b has no session
        assert await session_manager.validate_session("portal_a_profile") is True
        assert await session_manager.validate_session("portal_b_profile") is False

    @pytest.mark.asyncio
    async def test_overwrite_session(self, session_manager):
        """Saving a session twice should succeed and overwrite the first."""
        await session_manager.save_session("p1", portal="first")
        await session_manager.save_session("p1", portal="second")
        data = await session_manager.load_session("p1")
        assert data["portal"] == "second"

    @pytest.mark.asyncio
    async def test_orchestrator_idempotent_on_valid_session(
        self, orchestrator, session_manager
    ):
        """Authenticate twice with a valid session always returns session_loaded."""
        identity = _make_identity()
        await session_manager.save_session(identity.profile_id)

        r1 = await orchestrator.authenticate(identity)
        r2 = await orchestrator.authenticate(identity)

        assert r1.session_loaded is True
        assert r2.session_loaded is True

    @pytest.mark.asyncio
    async def test_credentials_never_logged(self, caplog):
        """Ensure password values do not appear in log output."""
        import logging

        secrets = MockSecretProvider(
            {"myportal_username": "alice", "myportal_password": "topsecret999"}
        )
        provider = CredentialProvider(secret_provider=secrets)

        with caplog.at_level(logging.DEBUG, logger="src.auth"):
            await provider.get_credentials("myportal")

        assert "topsecret999" not in caplog.text
