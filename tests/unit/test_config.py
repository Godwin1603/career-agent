import pytest
from pydantic import ValidationError

# All env vars required by Settings
_REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/db",
    "REDIS_URL": "redis://localhost/0",
    "GCP_PROJECT_ID": "test-project",
    "GCS_BUCKET_NAME": "test-bucket",
    "CLOUD_TASKS_LOCATION": "us-central1",
    "CLOUD_RUN_SERVICE_URL": "https://test.run.app",
    "CLOUD_TASKS_QUEUE_JOB_ENRICHMENT": "q1",
    "CLOUD_TASKS_QUEUE_PORTAL_APPLICATION": "q2",
    "CLOUD_TASKS_QUEUE_FORM_APPLICATION": "q3",
    "CLOUD_TASKS_QUEUE_EMAIL_APPLICATION": "q4",
    "CLOUD_TASKS_QUEUE_NOTIFICATION": "q5",
    "TELEGRAM_API_ID": "123",
    "TELEGRAM_API_HASH": "abc",
    "TELEGRAM_SESSION_STRING": "session",
    "TELEGRAM_CHANNEL_ID": "111",
    "TELEGRAM_NOTIFY_CHAT_ID": "222",
    "GMAIL_OAUTH_CLIENT_ID": "g1",
    "GMAIL_OAUTH_CLIENT_SECRET": "g2",
    "GMAIL_OAUTH_REFRESH_TOKEN": "g3",
    "GMAIL_SENDER_ADDRESS": "test@gmail.com",
}


def test_config_loads_from_env(monkeypatch):
    """
    Verifies that Settings correctly loads values from environment variables.
    monkeypatch.setenv restores the original environment after each test.
    """
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)

    from src.core.config import Settings

    settings = Settings()

    assert settings.DATABASE_URL == "postgresql+asyncpg://user:pass@localhost/db"
    assert settings.RELEVANCE_THRESHOLD == 65  # Default value
    assert settings.TELEGRAM_CHANNEL_ID == 111  # Cast to int


def test_config_fails_if_missing_required(monkeypatch):
    """
    Verifies that Settings raises ValidationError if required fields are missing.
    monkeypatch.delenv is scoped to this test only — process env is restored afterwards.
    """
    import os

    for key in list(os.environ.keys()):
        monkeypatch.delenv(key, raising=False)

    from src.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(_env_file=None)
