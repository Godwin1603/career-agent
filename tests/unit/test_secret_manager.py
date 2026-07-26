"""
Unit tests for GoogleSecretManagerProvider.

All GCP calls are mocked — no real Google APIs are invoked.
"""

import asyncio

import pytest

from src.auth.secrets import (
    GoogleSecretManagerProvider,
    MockSecretProvider,
    SecretNotFoundError,
    SecretProviderError,
)

# ---------------------------------------------------------------------------
# GoogleSecretManagerProvider — _sync_fetch mocked
# ---------------------------------------------------------------------------


class TestGoogleSecretManagerProvider:
    """Tests for the GCP Secret Manager integration."""

    def _make_provider(
        self,
        cache_ttl: float = 300.0,
        max_retries: int = 3,
    ) -> GoogleSecretManagerProvider:
        return GoogleSecretManagerProvider(
            project_id="test-project",
            cache_ttl_seconds=cache_ttl,
            max_retries=max_retries,
        )

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_fetch_returns_secret_value(self, monkeypatch):
        provider = self._make_provider()
        monkeypatch.setattr(provider, "_sync_fetch", lambda name: "s3cr3t")
        result = await provider.get_secret("my_secret")
        assert result == "s3cr3t"

    @pytest.mark.asyncio
    async def test_result_is_cached_on_second_call(self, monkeypatch):
        provider = self._make_provider()
        call_count = {"n": 0}

        def fake_fetch(name):
            call_count["n"] += 1
            return "cached_value"

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)
        await provider.get_secret("my_secret")
        await provider.get_secret("my_secret")
        assert call_count["n"] == 1

    @pytest.mark.asyncio
    async def test_cache_expires_after_ttl(self, monkeypatch):
        provider = self._make_provider(cache_ttl=0.01)
        call_count = {"n": 0}

        def fake_fetch(name):
            call_count["n"] += 1
            return "fresh"

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)
        await provider.get_secret("s")
        await asyncio.sleep(0.02)
        await provider.get_secret("s")
        assert call_count["n"] == 2

    # ------------------------------------------------------------------
    # Not-found (terminal)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_not_found_raises_terminal(self, monkeypatch):
        provider = self._make_provider(max_retries=1)

        def fake_fetch(name):
            raise SecretNotFoundError(f"Secret not found: {name!r}")

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)
        with pytest.raises(SecretNotFoundError):
            await provider.get_secret("missing_secret")

    @pytest.mark.asyncio
    async def test_not_found_is_not_retried(self, monkeypatch):
        provider = self._make_provider(max_retries=3)
        call_count = {"n": 0}

        def fake_fetch(name):
            call_count["n"] += 1
            raise SecretNotFoundError("nope")

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)
        with pytest.raises(SecretNotFoundError):
            await provider.get_secret("missing")
        assert call_count["n"] == 1  # no retries for terminal

    # ------------------------------------------------------------------
    # Transient errors (retryable)
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_transient_error_is_retried(self, monkeypatch):
        provider = self._make_provider(max_retries=3)
        call_count = {"n": 0}

        def fake_fetch(name):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise SecretProviderError("transient")
            return "eventually_ok"

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)

        async def noop_sleep(_):
            pass

        monkeypatch.setattr("asyncio.sleep", noop_sleep)
        result = await provider.get_secret("s")
        assert result == "eventually_ok"
        assert call_count["n"] == 3

    @pytest.mark.asyncio
    async def test_exhausted_retries_raise_provider_error(self, monkeypatch):
        provider = self._make_provider(max_retries=2)

        def fake_fetch(name):
            raise SecretProviderError("always fails")

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)

        async def noop_sleep(_):
            pass

        monkeypatch.setattr("asyncio.sleep", noop_sleep)
        with pytest.raises(SecretProviderError):
            await provider.get_secret("always_broken")

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_invalidate_specific_secret(self, monkeypatch):
        provider = self._make_provider()
        call_count = {"n": 0}

        def fake_fetch(name):
            call_count["n"] += 1
            return "val"

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)
        await provider.get_secret("key")
        provider.invalidate_cache("key")
        await provider.get_secret("key")
        assert call_count["n"] == 2

    @pytest.mark.asyncio
    async def test_invalidate_all(self, monkeypatch):
        provider = self._make_provider()
        call_count = {"n": 0}

        def fake_fetch(name):
            call_count["n"] += 1
            return "val"

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)
        await provider.get_secret("a")
        await provider.get_secret("b")
        provider.invalidate_cache()  # flush all
        await provider.get_secret("a")
        await provider.get_secret("b")
        assert call_count["n"] == 4

    # ------------------------------------------------------------------
    # Secret path construction
    # ------------------------------------------------------------------

    def test_secret_path_format(self):
        provider = self._make_provider()
        path = provider._build_secret_path("my_password")
        assert path == "projects/test-project/secrets/my_password/versions/latest"

    # ------------------------------------------------------------------
    # ImportError handling
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_import_error_raises_provider_error(self, monkeypatch):
        provider = self._make_provider(max_retries=1)

        def fake_fetch(name):
            raise SecretProviderError("google-cloud-secret-manager not installed")

        monkeypatch.setattr(provider, "_sync_fetch", fake_fetch)

        async def noop_sleep(_):
            pass

        monkeypatch.setattr("asyncio.sleep", noop_sleep)
        with pytest.raises(SecretProviderError):
            await provider.get_secret("any")


# ---------------------------------------------------------------------------
# Regression: MockSecretProvider still works after class addition
# ---------------------------------------------------------------------------


class TestMockSecretProviderRegression:
    @pytest.mark.asyncio
    async def test_mock_provider_still_works(self):
        provider = MockSecretProvider({"key": "value"})
        assert await provider.get_secret("key") == "value"

    @pytest.mark.asyncio
    async def test_mock_provider_not_found_still_raises(self):
        provider = MockSecretProvider()
        with pytest.raises(SecretNotFoundError):
            await provider.get_secret("missing")
