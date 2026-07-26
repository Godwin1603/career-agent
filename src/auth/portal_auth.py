"""
PortalAuthenticator — integrates AuthenticationOrchestrator with Playwright.

Bridges the deterministic auth flow from Phase 9 with actual browser-based
login using BrowserManager from Phase 8.

SCOPE
-----
- Session reuse via SessionManager (no login when session is valid)
- Username/password login when session is invalid
- Logout detection and automatic session invalidation
- Session persistence after successful login

OUT OF SCOPE (not implemented here)
-------------------------------------
- CAPTCHA bypass
- AI vision
- 2FA beyond OTP (e.g. hardware keys)

SECURITY
--------
Passwords are NEVER logged.
Cookies are NEVER logged.
Only portal, profile_id, and authentication outcome are surfaced in logs.
"""

import logging
from typing import Optional

from src.auth.credentials import MissingCredentialsError
from src.auth.dto import AuthenticationResult, AuthenticationState, IdentityContext
from src.auth.orchestrator import AuthenticationOrchestrator
from src.auth.otp import OTPService
from src.auth.session import SessionManager
from src.workers.playwright.browser import BrowserManager, BrowserSession

logger = logging.getLogger(__name__)

# Selectors used for username/password login — generic best-effort
_USERNAME_SELECTORS = [
    'input[type="email"]',
    'input[name="email"]',
    'input[name="username"]',
    'input[type="text"][autocomplete="username"]',
]
_PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
]
_SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'input[type="submit"]',
    'button:has-text("Sign in")',
    'button:has-text("Log in")',
    'button:has-text("Continue")',
]

# Patterns that indicate the user has been logged out
_LOGOUT_INDICATORS = [
    "sign in",
    "log in",
    "login",
    "sign up",
    "create account",
]


class PortalAuthenticationError(Exception):
    """Raised when portal authentication cannot be completed."""


class PortalAuthenticator:
    """
    Orchestrates browser-based login for portal strategies.

    This class is called by
    :class:`~src.workers.playwright.strategy.PlaywrightPortalStrategy`
    when a valid browser session does not exist.  It performs the following:

    1. Delegates to :class:`~src.auth.orchestrator.AuthenticationOrchestrator`
       for the deterministic pre-flight (credential check + session marker
       validation).
    2. If ``result.session_loaded``: returns immediately (existing session
       reused).
    3. If ``result.requires_login``: opens a browser, fills credentials,
       submits.
    4. After successful login: calls
       :meth:`~src.auth.session.SessionManager.save_session`.
    5. After failed login: calls
       :meth:`~src.auth.session.SessionManager.invalidate_session`.

    Args:
        orchestrator: The deterministic authentication orchestrator.
        browser_manager: Playwright browser lifecycle manager.
        session_manager: Session marker persistence.
        otp_service: Optional OTP service for portals requiring 2-step login.
        timeout_ms: Browser interaction timeout in milliseconds.
    """

    def __init__(
        self,
        orchestrator: AuthenticationOrchestrator,
        browser_manager: BrowserManager,
        session_manager: SessionManager,
        otp_service: Optional[OTPService] = None,
        timeout_ms: int = 30_000,
    ) -> None:
        self._orchestrator = orchestrator
        self._browser_manager = browser_manager
        self._session_manager = session_manager
        self._otp_service = otp_service
        self._timeout_ms = timeout_ms

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def ensure_authenticated(
        self,
        identity: IdentityContext,
        login_url: str,
    ) -> AuthenticationResult:
        """
        Ensure the browser profile for *identity* is authenticated.

        If a valid session exists, returns immediately with
        ``session_loaded=True``.  Otherwise performs a browser login
        and returns ``authenticated=True`` on success.

        Args:
            identity: Portal identity (portal, profile_id, username).
            login_url: URL of the portal login page.

        Returns:
            :class:`~src.auth.dto.AuthenticationResult`.
        """
        # Step 1: deterministic pre-flight (no browser opened yet)
        pre_result = await self._orchestrator.authenticate(identity)

        if not pre_result.success:
            # Terminal or retryable failure from orchestrator
            return pre_result

        if pre_result.session_loaded:
            logger.info(
                "Session reused — skipping browser login (portal=%r, profile_id=%r)",
                identity.portal,
                identity.profile_id,
            )
            return pre_result

        # Step 2: Session invalid — perform browser login
        return await self._browser_login(identity, login_url)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _browser_login(
        self,
        identity: IdentityContext,
        login_url: str,
    ) -> AuthenticationResult:
        """Open a browser session and perform username/password login."""
        portal = identity.portal
        profile_id = identity.profile_id

        # Re-load credentials for the actual login (reference is held only
        # within this method and deleted before return — H-01 equivalent).
        try:
            cred = await self._orchestrator._credential_provider.get_credentials(portal)
        except MissingCredentialsError as exc:
            return AuthenticationResult(
                success=False,
                failure_reason=str(exc),
                metadata={"state": AuthenticationState.missing_credentials},
            )

        session: Optional[BrowserSession] = None
        try:
            session = await self._browser_manager.create_session(
                profile_id=profile_id, headless=True
            )
            page = session.page

            logger.info(
                "Navigating to login page (portal=%r, profile_id=%r)",
                portal,
                profile_id,
            )
            await page.goto(login_url, timeout=self._timeout_ms)
            await page.wait_for_load_state("domcontentloaded")

            # Check for logout indicator on the current page
            if await self._is_logged_out(page):
                await self._fill_login_form(page, cred.username, cred.get_password())

                # Handle optional OTP step
                if self._otp_service and await self._has_otp_prompt(page):
                    otp = await self._otp_service.wait_for_otp(
                        portal, timeout_seconds=60.0
                    )
                    await self._fill_otp(page, otp)
                    del otp  # H-01: release immediately

            del cred  # H-01: release credential reference immediately

            # Validate login success by checking for logout indicators
            await page.wait_for_load_state("networkidle", timeout=self._timeout_ms)
            if await self._is_logged_out(page):
                # Login failed (wrong credentials or unexpected redirect)
                await self._session_manager.invalidate_session(profile_id)
                logger.warning(
                    "Login failed — logout indicator still present "
                    "(portal=%r, profile_id=%r)",
                    portal,
                    profile_id,
                )
                return AuthenticationResult(
                    success=False,
                    failure_reason="login failed: portal still showing login page",
                    metadata={"state": AuthenticationState.retryable_failure},
                )

            # Persist session marker
            await self._session_manager.save_session(
                profile_id=profile_id, portal=portal
            )
            logger.info(
                "Login successful (portal=%r, profile_id=%r)", portal, profile_id
            )
            return AuthenticationResult(
                success=True,
                authenticated=True,
                metadata={
                    "state": AuthenticationState.authenticated,
                    "portal": portal,
                    "profile_id": profile_id,
                },
            )

        except Exception as exc:
            # Ensure credential reference is gone even on unexpected exceptions.
            # Using locals().pop avoids an F821 undefined-name lint warning.
            locals().pop("cred", None)
            logger.warning(
                "Browser login error (portal=%r, profile_id=%r): %s",
                portal,
                profile_id,
                type(exc).__name__,
            )
            return AuthenticationResult(
                success=False,
                failure_reason=f"browser login error: {type(exc).__name__}",
                metadata={"state": AuthenticationState.retryable_failure},
            )
        finally:
            if session is not None:
                await self._browser_manager.close_session(session)

    async def _is_logged_out(self, page) -> bool:
        """Return True when any logout indicator is visible on the page."""
        try:
            title = (await page.title()).lower()
            url = page.url.lower()
            for indicator in _LOGOUT_INDICATORS:
                if indicator in title or indicator in url:
                    return True
            return False
        except Exception:
            return False

    async def _has_otp_prompt(self, page) -> bool:
        """Return True when an OTP input field is visible."""
        try:
            for selector in [
                'input[name="otp"]',
                'input[name="code"]',
                'input[autocomplete="one-time-code"]',
            ]:
                if await page.locator(selector).count() > 0:
                    return True
            return False
        except Exception:
            return False

    async def _fill_login_form(self, page, username: str, password: str) -> None:
        """Fill and submit the login form. Credentials are NEVER logged."""
        # Username field
        for sel in _USERNAME_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.fill(username)
                break

        # Password field
        for sel in _PASSWORD_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.fill(password)
                break

        # Submit
        for sel in _SUBMIT_SELECTORS:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.click()
                break

    async def _fill_otp(self, page, otp: str) -> None:
        """Fill the OTP field. OTP is NEVER logged."""
        for sel in [
            'input[name="otp"]',
            'input[name="code"]',
            'input[autocomplete="one-time-code"]',
        ]:
            loc = page.locator(sel)
            if await loc.count() > 0:
                await loc.first.fill(otp)
                submit = page.locator('button[type="submit"]')
                if await submit.count() > 0:
                    await submit.first.click()
                break
