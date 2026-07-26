"""
Authentication and Identity DTOs.

AuthenticationResult and IdentityContext are the primary data transfer
objects for the authentication layer.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AuthenticationState(str, Enum):
    """
    Represents the current state of an authentication attempt.
    """

    # Session loaded successfully from disk — no login required
    session_loaded = "session_loaded"

    # Credentials obtained, login is required
    requires_login = "requires_login"

    # Successfully authenticated (session was created or refreshed)
    authenticated = "authenticated"

    # Credentials could not be obtained
    missing_credentials = "missing_credentials"

    # Session or profile invalid/corrupt
    invalid_session = "invalid_session"

    # Portal is not supported by this implementation
    unsupported_portal = "unsupported_portal"

    # A transient error occurred that is worth retrying
    retryable_failure = "retryable_failure"


class IdentityContext(BaseModel):
    """
    Immutable identity context passed around the authentication layer.

    Holds enough information to route credential and session lookups
    without exposing secret values.
    """

    model_config = {"frozen": True}

    portal: str
    profile_id: str
    username: str

    def __repr__(self) -> str:
        # Intentionally exclude sensitive fields from repr.
        return (
            f"IdentityContext(portal={self.portal!r}, profile_id={self.profile_id!r})"
        )


class AuthenticationResult(BaseModel):
    """
    Result returned by the authentication orchestrator.

    success: True when the caller may proceed with portal automation.
    authenticated: True when a fresh login was performed.
    requires_login: True when the session was not reusable.
    session_loaded: True when an existing session was reused.
    failure_reason: Human-readable description for failures.
    metadata: Non-sensitive supplementary data.
    """

    model_config = {"frozen": True}

    success: bool
    authenticated: bool = False
    requires_login: bool = False
    session_loaded: bool = False
    failure_reason: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
