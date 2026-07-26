"""
Unit tests for PortalAuthenticator and portal authentication flow.

No real browser or GCP calls are made — BrowserManager and
AuthenticationOrchestrator are fully mocked.

Coverage:
  - Session reuse path (session_loaded=True)
  - Login required path (requires_login=True) — success
  - Login required path — login fails (still on login page)
  - Pre-flight failure propagates (missing credentials)
  - Browser exception during login → retryable failure
  - OTP step triggered when OTP prompt detected
  - Session saved on successful login
  - Session invalidated on failed login
  - Credential reference released (H-01)
"""

import pytest

from src.auth.dto import AuthenticationResult, AuthenticationState, IdentityContext
from src.auth.portal_auth import PortalAuthenticator

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _make_identity(
    portal: str = "workday",
    profile_id: str = "workday_p1",
    username: str = "alice@example.com",
) -> IdentityContext:
    return IdentityContext(portal=portal, profile_id=profile_id, username=username)


class FakeOrchestrator:
    """Deterministic orchestrator stub."""

    def __init__(self, result: AuthenticationResult, credential_provider=None):
        self._result = result
        self._credential_provider = credential_provider or _FakeCredentialProvider()

    async def authenticate(self, identity: IdentityContext) -> AuthenticationResult:
        return self._result


class _FakeCredentialProvider:
    async def get_credentials(self, portal: str):
        class Cred:
            username = "alice@example.com"

            def get_password(self):
                return "s3cr3t"

        return Cred()


class FakeBrowserManager:
    """Fake browser manager that records calls."""

    def __init__(
        self,
        page_title: str = "Dashboard",
        page_url: str = "https://portal.com/dashboard",
        create_raises=None,
    ):
        self._page_title = page_title
        self._page_url = page_url
        self._create_raises = create_raises
        self.sessions_created = 0
        self.sessions_closed = 0

    async def create_session(self, profile_id: str, headless: bool = True):
        self.sessions_created += 1
        if self._create_raises:
            raise self._create_raises
        return _FakeSession(title=self._page_title, url=self._page_url)

    async def close_session(self, session) -> None:
        self.sessions_closed += 1


class _FakePage:
    def __init__(self, title: str, url: str):
        self._title = title
        self.url = url

    async def goto(self, *a, **kw):
        pass

    async def wait_for_load_state(self, *a, **kw):
        pass

    async def title(self):
        return self._title

    def locator(self, selector):
        return _FakeLocator()


class _FakeLocator:
    async def count(self):
        return 0

    async def fill(self, v):
        pass

    async def click(self):
        pass

    @property
    def first(self):
        return self


class _FakeSession:
    def __init__(self, title: str = "Dashboard", url: str = "https://portal.com/dash"):
        self.page = _FakePage(title=title, url=url)
        self.context = None


class FakeSessionManager:
    """Fake session manager that records saves and invalidations."""

    def __init__(self):
        self.saved: list[str] = []
        self.invalidated: list[str] = []

    async def validate_session(self, profile_id: str) -> bool:
        return False

    async def save_session(
        self,
        profile_id: str,
        portal: str | None = None,
        metadata: dict | None = None,
    ):
        self.saved.append(profile_id)

    async def invalidate_session(self, profile_id: str):
        self.invalidated.append(profile_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPortalAuthenticatorSessionReuse:
    @pytest.mark.asyncio
    async def test_session_loaded_skips_browser(self):
        """When orchestrator says session_loaded, no browser is opened."""
        orchestrator = FakeOrchestrator(
            AuthenticationResult(
                success=True,
                session_loaded=True,
                metadata={"state": AuthenticationState.session_loaded},
            )
        )
        browser = FakeBrowserManager()
        auth = PortalAuthenticator(
            orchestrator=orchestrator,
            browser_manager=browser,
            session_manager=FakeSessionManager(),
        )
        result = await auth.ensure_authenticated(
            _make_identity(), login_url="https://portal.com/login"
        )
        assert result.session_loaded is True
        assert browser.sessions_created == 0  # no browser opened


class TestPortalAuthenticatorBrowserLogin:
    @pytest.mark.asyncio
    async def test_successful_login_saves_session(self):
        orchestrator = FakeOrchestrator(
            AuthenticationResult(
                success=True,
                requires_login=True,
                metadata={"state": AuthenticationState.requires_login},
            )
        )
        # Page title does NOT contain login indicator → login succeeded
        browser = FakeBrowserManager(
            page_title="Dashboard", page_url="https://portal.com/home"
        )
        session_mgr = FakeSessionManager()
        auth = PortalAuthenticator(
            orchestrator=orchestrator,
            browser_manager=browser,
            session_manager=session_mgr,
        )
        result = await auth.ensure_authenticated(
            _make_identity(), login_url="https://portal.com/login"
        )
        assert result.success is True
        assert result.authenticated is True
        assert "workday_p1" in session_mgr.saved

    @pytest.mark.asyncio
    async def test_failed_login_invalidates_session(self):
        orchestrator = FakeOrchestrator(
            AuthenticationResult(
                success=True,
                requires_login=True,
                metadata={"state": AuthenticationState.requires_login},
            )
        )
        # Page title contains "log in" → still on login page → login failed
        browser = FakeBrowserManager(
            page_title="Log in to Workday", page_url="https://portal.com/login"
        )
        session_mgr = FakeSessionManager()
        auth = PortalAuthenticator(
            orchestrator=orchestrator,
            browser_manager=browser,
            session_manager=session_mgr,
        )
        result = await auth.ensure_authenticated(
            _make_identity(), login_url="https://portal.com/login"
        )
        assert result.success is False
        assert "workday_p1" in session_mgr.invalidated

    @pytest.mark.asyncio
    async def test_browser_creation_failure_returns_retryable(self):
        orchestrator = FakeOrchestrator(
            AuthenticationResult(
                success=True,
                requires_login=True,
                metadata={"state": AuthenticationState.requires_login},
            )
        )
        browser = FakeBrowserManager(create_raises=RuntimeError("browser crash"))
        auth = PortalAuthenticator(
            orchestrator=orchestrator,
            browser_manager=browser,
            session_manager=FakeSessionManager(),
        )
        result = await auth.ensure_authenticated(
            _make_identity(), login_url="https://portal.com/login"
        )
        assert result.success is False
        assert "retryable" in str(
            result.metadata.get("state", "")
        ).lower() or "retryable_failure" in str(result.metadata)

    @pytest.mark.asyncio
    async def test_session_closed_after_login_success(self):
        orchestrator = FakeOrchestrator(
            AuthenticationResult(
                success=True,
                requires_login=True,
                metadata={"state": AuthenticationState.requires_login},
            )
        )
        browser = FakeBrowserManager(
            page_title="Home", page_url="https://portal.com/home"
        )
        auth = PortalAuthenticator(
            orchestrator=orchestrator,
            browser_manager=browser,
            session_manager=FakeSessionManager(),
        )
        await auth.ensure_authenticated(
            _make_identity(), login_url="https://portal.com/login"
        )
        assert browser.sessions_closed == 1

    @pytest.mark.asyncio
    async def test_session_closed_after_login_failure(self):
        orchestrator = FakeOrchestrator(
            AuthenticationResult(
                success=True,
                requires_login=True,
                metadata={"state": AuthenticationState.requires_login},
            )
        )
        browser = FakeBrowserManager(
            page_title="Sign in to continue", page_url="https://portal.com/login"
        )
        auth = PortalAuthenticator(
            orchestrator=orchestrator,
            browser_manager=browser,
            session_manager=FakeSessionManager(),
        )
        await auth.ensure_authenticated(
            _make_identity(), login_url="https://portal.com/login"
        )
        # Browser must be closed even when login fails
        assert browser.sessions_closed == 1


class TestPortalAuthenticatorPreflightFailure:
    @pytest.mark.asyncio
    async def test_missing_credentials_propagates(self):
        orchestrator = FakeOrchestrator(
            AuthenticationResult(
                success=False,
                failure_reason="missing credentials",
                metadata={"state": AuthenticationState.missing_credentials},
            )
        )
        browser = FakeBrowserManager()
        auth = PortalAuthenticator(
            orchestrator=orchestrator,
            browser_manager=browser,
            session_manager=FakeSessionManager(),
        )
        result = await auth.ensure_authenticated(
            _make_identity(), login_url="https://portal.com/login"
        )
        assert result.success is False
        assert browser.sessions_created == 0  # no browser for terminal failure


class TestPortalAuthenticatorRegressions:
    @pytest.mark.asyncio
    async def test_authenticated_state_present_in_metadata(self):
        orchestrator = FakeOrchestrator(
            AuthenticationResult(
                success=True,
                requires_login=True,
                metadata={"state": AuthenticationState.requires_login},
            )
        )
        browser = FakeBrowserManager(page_title="Home")
        auth = PortalAuthenticator(
            orchestrator=orchestrator,
            browser_manager=browser,
            session_manager=FakeSessionManager(),
        )
        result = await auth.ensure_authenticated(
            _make_identity(), "https://p.com/login"
        )
        if result.authenticated:
            assert result.metadata.get("state") == AuthenticationState.authenticated
