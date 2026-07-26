"""
Secret Provider abstraction and mock implementation.

The SecretProvider interface decouples the rest of the auth layer from
any concrete secrets back-end (e.g. Google Secret Manager, env vars,
Vault, etc.).

Phase 9 ships a MockSecretProvider suitable for local development and
unit tests.  The real Google Secret Manager implementation is deferred
to a future phase.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class SecretNotFoundError(Exception):
    """Raised when a requested secret does not exist in the provider."""


class SecretProviderError(Exception):
    """
    Raised when the secret provider itself fails transiently.
    Callers should treat this as a retryable condition.
    """


class SecretProvider(ABC):
    """
    Abstract interface for retrieving secrets.

    Implementations MUST NOT log secret values.
    """

    @abstractmethod
    async def get_secret(self, name: str) -> str:
        """
        Return the secret value for *name*.

        Raises:
            SecretNotFoundError: when the secret does not exist.
            SecretProviderError: when a transient provider failure occurs.
        """
        ...


class MockSecretProvider(SecretProvider):
    """
    In-memory secret store used for development and unit testing.

    Secrets are provided via the constructor and are never written to logs.

    Usage::

        provider = MockSecretProvider({"portal_x_password": "s3cr3t"})
        value = await provider.get_secret("portal_x_password")
    """

    def __init__(self, secrets: Optional[dict[str, str]] = None) -> None:
        self._secrets: dict[str, str] = secrets or {}

    async def get_secret(self, name: str) -> str:
        if name not in self._secrets:
            raise SecretNotFoundError(f"Secret not found: {name!r}")
        logger.debug("MockSecretProvider: secret retrieved (name=%r)", name)
        return self._secrets[name]

    # ------------------------------------------------------------------
    # Helpers for testing
    # ------------------------------------------------------------------

    def set_secret(self, name: str, value: str) -> None:
        """Add or overwrite a secret (test helper only)."""
        self._secrets[name] = value

    def remove_secret(self, name: str) -> None:
        """Remove a secret (test helper only)."""
        self._secrets.pop(name, None)
