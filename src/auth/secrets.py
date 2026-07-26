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

    DETERMINISTIC BEHAVIOUR
    -----------------------
    - Secrets are stored in the dict supplied to the constructor.
    - ``get_secret(name)`` returns the value for *name* synchronously
      (wrapped in a coroutine); it never performs I/O.
    - If *name* is absent, :class:`SecretNotFoundError` is raised — no
      fallback, no default, no partial match.
    - ``set_secret`` / ``remove_secret`` mutate the in-memory store
      immediately and are visible to any subsequent ``get_secret`` call
      within the same instance.
    - No randomness, no network calls, no side effects outside the instance.

    Secrets are never written to logs.

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


class GoogleSecretManagerProvider(SecretProvider):
    """
    Google Secret Manager implementation of SecretProvider.

    Fetches secrets from GCP Secret Manager using the official client library.
    Secrets are cached in memory for *cache_ttl_seconds* to reduce API calls.
    The cache is never persisted to disk.

    SECURITY
    --------
    - Secret values are NEVER logged.
    - Cache entries are plain strings in process memory; no external storage.
    - On transient GCP errors the call is retried up to *max_retries* times
      with exponential back-off before raising :class:`SecretProviderError`.

    Args:
        project_id: GCP project containing the secrets.
        cache_ttl_seconds: How long a cached value remains valid (default 300 s).
        max_retries: Number of retry attempts on transient errors (default 3).
    """

    def __init__(
        self,
        project_id: str,
        cache_ttl_seconds: float = 300.0,
        max_retries: int = 3,
    ) -> None:
        self._project_id = project_id
        self._cache_ttl = cache_ttl_seconds
        self._max_retries = max_retries
        # {secret_name: (value, fetched_at_monotonic)}
        self._cache: dict[str, tuple[str, float]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_cached(self, name: str) -> bool:
        import time

        if name not in self._cache:
            return False
        _, fetched_at = self._cache[name]
        return (time.monotonic() - fetched_at) < self._cache_ttl

    def _get_cached(self, name: str) -> str:
        value, _ = self._cache[name]
        return value

    def _store_cache(self, name: str, value: str) -> None:
        import time

        self._cache[name] = (value, time.monotonic())

    def _build_secret_path(self, name: str) -> str:
        return f"projects/{self._project_id}/secrets/{name}/versions/latest"

    # ------------------------------------------------------------------
    # SecretProvider implementation
    # ------------------------------------------------------------------

    async def get_secret(self, name: str) -> str:
        """
        Fetch the latest version of *name* from Google Secret Manager.

        Results are cached for *cache_ttl_seconds*.  On transient GCP errors
        the request is retried up to *max_retries* times.

        Raises:
            SecretNotFoundError: when the secret does not exist (404).
            SecretProviderError: when a transient GCP error persists after
                all retries.
        """
        import asyncio

        if self._is_cached(name):
            logger.debug("SecretManager cache hit (name=%r)", name)
            return self._get_cached(name)

        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(1, self._max_retries + 1):
            try:
                value = await self._fetch_from_gcp(name)
                self._store_cache(name, value)
                logger.info(
                    "Secret fetched from SecretManager (name=%r, attempt=%d)",
                    name,
                    attempt,
                )
                return value
            except SecretNotFoundError:
                # Not-found is terminal — do not retry
                raise
            except SecretProviderError:
                last_exc = SecretProviderError(
                    f"Transient GCP error for secret={name!r} after {attempt} attempts"
                )
                if attempt < self._max_retries:
                    backoff = 2 ** (attempt - 1)
                    logger.warning(
                        "SecretManager transient error (name=%r, attempt=%d/%d), "
                        "retrying in %ds",
                        name,
                        attempt,
                        self._max_retries,
                        backoff,
                    )
                    await asyncio.sleep(backoff)

        raise last_exc

    async def _fetch_from_gcp(self, name: str) -> str:
        """
        Perform the actual GCP API call in a thread pool executor to keep
        the event loop non-blocking (the official client is synchronous).
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_fetch, name)

    def _sync_fetch(self, name: str) -> str:
        """
        Synchronous GCP Secret Manager fetch.  Runs in a thread pool.
        Raises SecretNotFoundError or SecretProviderError as appropriate.
        """
        try:
            # Import here to keep the dependency optional / lazy
            from google.cloud import secretmanager

            client = secretmanager.SecretManagerServiceClient()
            secret_path = self._build_secret_path(name)
            response = client.access_secret_version(name=secret_path)
            # The payload is bytes — decode to str
            return response.payload.data.decode("utf-8")

        except ImportError:
            raise SecretProviderError(
                "google-cloud-secret-manager is not installed. "
                "Install it with: pip install google-cloud-secret-manager"
            )
        except Exception as exc:
            # Map GCP-specific not-found to SecretNotFoundError
            exc_name = type(exc).__name__
            exc_str = str(exc).lower()
            if "notfound" in exc_name or "404" in exc_str or "not found" in exc_str:
                raise SecretNotFoundError(f"Secret not found: {name!r}") from exc
            # All other GCP errors are treated as transient
            raise SecretProviderError(
                f"GCP Secret Manager error for {name!r}: {exc}"
            ) from exc

    def invalidate_cache(self, name: Optional[str] = None) -> None:
        """
        Manually invalidate the cache.

        Args:
            name: Specific secret to evict.  Pass ``None`` to flush all.
        """
        if name is None:
            self._cache.clear()
            logger.debug("SecretManager cache fully flushed")
        elif name in self._cache:
            del self._cache[name]
            logger.debug("SecretManager cache evicted (name=%r)", name)
