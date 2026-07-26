"""
Authentication Orchestrator.

Coordinates credential loading, session management, and the overall
authentication flow.  This orchestrator is deterministic and does NOT
perform actual browser login — that responsibility belongs to a future
phase that extends PlaywrightPortalStrategy.

Flow::

    1. Validate IdentityContext
    2. Load credentials via CredentialProvider
    3. Load session state via SessionManager
    4. Validate session
    5. If session valid  → return AuthenticationResult(session_loaded=True)
    6. If session invalid → return AuthenticationResult(requires_login=True)

The caller (e.g. a future portal strategy) is responsible for
performing the actual browser login when requires_login=True.

ERROR CLASSIFICATION
--------------------
Retryable:
  CredentialProviderError  — transient secret provider failure
  SessionError             — transient session I/O failure

Terminal:
  MissingCredentialsError  — credentials absent for portal
  ValueError               — invalid IdentityContext
"""

import logging

from src.auth.credentials import (
    CredentialProvider,
    CredentialProviderError,
    MissingCredentialsError,
)
from src.auth.dto import AuthenticationResult, AuthenticationState, IdentityContext
from src.auth.session import SessionError, SessionManager

logger = logging.getLogger(__name__)


class AuthenticationOrchestrator:
    """
    Deterministic authentication flow controller.

    All collaborators are injected, making the orchestrator easily
    testable without real secrets or a real file-system.

    Args:
        credential_provider: Provides portal credentials.
        session_manager: Manages browser session markers.
    """

    def __init__(
        self,
        credential_provider: CredentialProvider,
        session_manager: SessionManager,
    ) -> None:
        self._credential_provider = credential_provider
        self._session_manager = session_manager

    async def authenticate(
        self,
        identity: IdentityContext,
    ) -> AuthenticationResult:
        """
        Run the authentication flow for *identity*.

        Returns an :class:`AuthenticationResult` that tells the caller
        whether a fresh login is required (``requires_login=True``) or
        whether an existing session was reused (``session_loaded=True``).

        Only ``portal`` and ``profile_id`` are included in log statements;
        usernames, passwords, and session data are never logged.
        """
        portal = identity.portal
        profile_id = identity.profile_id

        # ── Step 1: Validate identity ──────────────────────────────────
        if not portal or not profile_id:
            logger.error(
                "Authentication failed — invalid identity context "
                "(portal=%r, profile_id=%r)",
                portal,
                profile_id,
            )
            return AuthenticationResult(
                success=False,
                failure_reason=(
                    "invalid identity context: portal and profile_id are required"
                ),
                metadata={"state": AuthenticationState.retryable_failure},
            )

        # ── Step 2: Load credentials ───────────────────────────────────
        try:
            await self._credential_provider.get_credentials(portal)
        except MissingCredentialsError as exc:
            logger.error(
                "Authentication failed — missing credentials (portal=%r): %s",
                portal,
                type(exc).__name__,
            )
            return AuthenticationResult(
                success=False,
                failure_reason=str(exc),
                metadata={"state": AuthenticationState.missing_credentials},
            )
        except CredentialProviderError as exc:
            logger.warning(
                "Authentication failed — transient credential error (portal=%r): %s",
                portal,
                type(exc).__name__,
            )
            return AuthenticationResult(
                success=False,
                failure_reason=f"retryable credential provider error: {exc}",
                metadata={"state": AuthenticationState.retryable_failure},
            )

        # ── Step 3: Validate session ───────────────────────────────────
        try:
            session_valid = await self._session_manager.validate_session(profile_id)
        except SessionError as exc:
            logger.warning(
                "Session validation error (portal=%r, profile_id=%r): %s",
                portal,
                profile_id,
                type(exc).__name__,
            )
            return AuthenticationResult(
                success=False,
                failure_reason=f"retryable session error: {exc}",
                metadata={"state": AuthenticationState.retryable_failure},
            )

        if session_valid:
            # Existing session is reusable — no login needed
            logger.info(
                "Session reused (portal=%r, profile_id=%r)",
                portal,
                profile_id,
            )
            return AuthenticationResult(
                success=True,
                session_loaded=True,
                metadata={
                    "state": AuthenticationState.session_loaded,
                    "portal": portal,
                    "profile_id": profile_id,
                    "username": identity.username,
                },
            )

        # ── Step 4: Session invalid — caller must perform login ────────
        logger.info(
            "Login required (portal=%r, profile_id=%r)",
            portal,
            profile_id,
        )
        return AuthenticationResult(
            success=True,
            requires_login=True,
            metadata={
                "state": AuthenticationState.requires_login,
                "portal": portal,
                "profile_id": profile_id,
                "username": identity.username,
            },
        )
