"""
Startup validation for career-agent.

Validates that all required environment variables are present and that
critical services are reachable before the application begins serving traffic.

Failures during startup validation raise ``StartupError``, which causes
the FastAPI lifespan to abort and the process to exit non-zero.

SCOPE
-----
- Required settings validation (no placeholders, no empty strings)
- Database connectivity probe
- Gmail configuration check (fields present, no connectivity test)
- GCP project ID presence check

NOT IN SCOPE
------------
- Playwright browser validation (browser is launched on demand)
- Full Gmail OAuth token validation (token refresh is deferred to first use)
- Secret Manager validation (secrets are fetched lazily)
"""

import logging

logger = logging.getLogger(__name__)

# Settings fields that MUST be non-empty for the service to start
_REQUIRED_SETTINGS = [
    "DATABASE_URL",
    "GCP_PROJECT_ID",
    "CLOUD_TASKS_LOCATION",
    "CLOUD_RUN_SERVICE_URL",
    "CLOUD_TASKS_QUEUE_PORTAL_APPLICATION",
    "CLOUD_TASKS_QUEUE_FORM_APPLICATION",
    "CLOUD_TASKS_QUEUE_EMAIL_APPLICATION",
    "GMAIL_OAUTH_CLIENT_ID",
    "GMAIL_OAUTH_CLIENT_SECRET",
    "GMAIL_OAUTH_REFRESH_TOKEN",
    "GMAIL_SENDER_ADDRESS",
]

# Settings that are validated but permitted to be absent in test mode
_OPTIONAL_SETTINGS = [
    "REDIS_URL",
    "GCS_BUCKET_NAME",
    "CLOUD_TASKS_QUEUE_JOB_ENRICHMENT",
    "CLOUD_TASKS_QUEUE_NOTIFICATION",
]


class StartupError(Exception):
    """
    Raised when the application cannot start due to misconfiguration
    or a dependency that is unavailable.
    """


class StartupValidator:
    """
    Performs pre-flight checks before the application begins serving.

    Usage::

        validator = StartupValidator()
        await validator.validate()
    """

    def __init__(self, skip_db_probe: bool = False) -> None:
        self._skip_db_probe = skip_db_probe

    async def validate(self) -> None:
        """
        Run all startup checks.  Raises :class:`StartupError` on the first
        critical failure encountered.
        """
        logger.info("Running startup validation…")
        self._validate_settings()
        if not self._skip_db_probe:
            await self._probe_database()
        logger.info("Startup validation passed.")

    # ------------------------------------------------------------------
    # Settings validation
    # ------------------------------------------------------------------

    def _validate_settings(self) -> None:
        """Raise StartupError when any required setting is missing or empty."""
        try:
            from src.core.config import settings
        except Exception as exc:
            raise StartupError(
                f"Failed to load settings: {exc}.  "
                "Ensure all required environment variables are set."
            ) from exc

        missing: list[str] = []
        for field in _REQUIRED_SETTINGS:
            value = getattr(settings, field, None)
            if not value or (isinstance(value, str) and not value.strip()):
                missing.append(field)

        if missing:
            raise StartupError(
                f"Missing or empty required settings: {missing}.  "
                "Set these environment variables before starting the service."
            )

        logger.info(
            "Settings validation passed (%d required fields OK)",
            len(_REQUIRED_SETTINGS),
        )

    # ------------------------------------------------------------------
    # Database connectivity probe
    # ------------------------------------------------------------------

    async def _probe_database(self) -> None:
        """Issue a lightweight ``SELECT 1`` to verify DB connectivity."""
        try:
            from sqlalchemy import text

            from src.core.database import engine

            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Database connectivity probe passed.")
        except Exception as exc:
            raise StartupError(
                f"Database connectivity probe failed: {type(exc).__name__}.  "
                "Ensure DATABASE_URL points to a reachable PostgreSQL instance."
            ) from exc


# ---------------------------------------------------------------------------
# Dependency health checks (used by /health/ready)
# ---------------------------------------------------------------------------


async def check_database_health() -> dict:
    """
    Return a health status dict for the database.

    Returns:
        ``{"status": "healthy", "database": "connected"}`` on success.
        ``{"status": "unhealthy", "database": "disconnected",
        "error": "..."}`` on failure.
    """
    try:
        from sqlalchemy import text

        from src.core.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as exc:
        return {
            "status": "unhealthy",
            "database": "disconnected",
            "error": type(exc).__name__,
        }


async def check_gmail_config_health() -> dict:
    """
    Return a health status dict for Gmail configuration.

    Only checks that the required OAuth fields are non-empty — does NOT
    make network requests during the health check.
    """
    try:
        from src.core.config import settings

        required = [
            settings.GMAIL_OAUTH_CLIENT_ID,
            settings.GMAIL_OAUTH_CLIENT_SECRET,
            settings.GMAIL_OAUTH_REFRESH_TOKEN,
            settings.GMAIL_SENDER_ADDRESS,
        ]
        if all(required):
            return {"status": "healthy", "gmail": "configured"}
        return {"status": "degraded", "gmail": "partially_configured"}
    except Exception as exc:
        return {
            "status": "unhealthy",
            "gmail": "misconfigured",
            "error": type(exc).__name__,
        }
