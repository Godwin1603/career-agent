"""
CredentialProvider — resolves portal credentials via a SecretProvider.

Credentials are returned as immutable dataclass instances.
Secret values are NEVER logged; only the credential name is recorded.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.auth.secrets import SecretNotFoundError, SecretProvider, SecretProviderError

logger = logging.getLogger(__name__)

# Naming convention for secrets:
#   <portal>_username
#   <portal>_password
_USERNAME_SUFFIX = "_username"
_PASSWORD_SUFFIX = "_password"


class MissingCredentialsError(Exception):
    """Raised when required credentials cannot be found for a portal."""


class CredentialProviderError(Exception):
    """
    Raised when the underlying secret provider fails transiently.
    Callers should treat this as a retryable condition.
    """


@dataclass(frozen=True)
class PortalCredential:
    """
    Immutable credential object for a single portal.

    The __repr__ is intentionally masked so that passwords are never
    captured in logs or tracebacks.
    """

    portal: str
    username: str
    _password: str

    def get_password(self) -> str:
        """Return the raw password.  Do not log the return value."""
        return self._password

    def __repr__(self) -> str:
        # Password is intentionally masked so it never appears in logs.
        return (
            f"PortalCredential(portal={self.portal!r}, "
            f"username={self.username!r}, password=***)"
        )


class CredentialProvider:
    """
    Obtains portal credentials through a SecretProvider.

    Secret names follow the convention::

        <portal>_username
        <portal>_password

    Example::

        provider = CredentialProvider(secret_provider=MockSecretProvider({
            "myportal_username": "alice@example.com",
            "myportal_password": "s3cr3t",
        }))
        cred = await provider.get_credentials("myportal")
    """

    def __init__(self, secret_provider: SecretProvider) -> None:
        self._secret_provider = secret_provider

    async def get_credentials(
        self,
        portal: str,
        username_key: Optional[str] = None,
        password_key: Optional[str] = None,
    ) -> PortalCredential:
        """
        Retrieve credentials for *portal*.

        Args:
            portal: Identifier of the target portal (e.g. ``"workday"``).
            username_key: Override the default secret name for the username.
            password_key: Override the default secret name for the password.

        Returns:
            An immutable :class:`PortalCredential`.

        Raises:
            MissingCredentialsError: when credentials are absent (terminal).
            CredentialProviderError: when a transient provider error occurs
                (retryable).
        """
        if not portal:
            raise MissingCredentialsError("portal identifier must not be empty")

        u_key = username_key or f"{portal}{_USERNAME_SUFFIX}"
        p_key = password_key or f"{portal}{_PASSWORD_SUFFIX}"

        try:
            username = await self._secret_provider.get_secret(u_key)
        except SecretNotFoundError:
            raise MissingCredentialsError(
                f"Username credential not found for portal={portal!r} (key={u_key!r})"
            )
        except SecretProviderError as exc:
            raise CredentialProviderError(
                f"Transient error fetching username for portal={portal!r}: {exc}"
            ) from exc

        try:
            password = await self._secret_provider.get_secret(p_key)
        except SecretNotFoundError:
            raise MissingCredentialsError(
                f"Password credential not found for portal={portal!r} (key={p_key!r})"
            )
        except SecretProviderError as exc:
            raise CredentialProviderError(
                f"Transient error fetching password for portal={portal!r}: {exc}"
            ) from exc

        logger.info(
            "Credentials loaded (portal=%r, username_key=%r)",
            portal,
            u_key,
        )
        return PortalCredential(portal=portal, username=username, _password=password)
