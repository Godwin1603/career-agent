from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables.
    All required fields must be provided in the environment.
    """

    # Database
    DATABASE_URL: str

    # Redis
    REDIS_URL: str

    # Google Cloud Platform
    GCP_PROJECT_ID: str
    GCS_BUCKET_NAME: str
    CLOUD_TASKS_LOCATION: str
    CLOUD_RUN_SERVICE_URL: str

    # Cloud Tasks Queue Names
    CLOUD_TASKS_QUEUE_JOB_ENRICHMENT: str
    CLOUD_TASKS_QUEUE_PORTAL_APPLICATION: str
    CLOUD_TASKS_QUEUE_FORM_APPLICATION: str
    CLOUD_TASKS_QUEUE_EMAIL_APPLICATION: str
    CLOUD_TASKS_QUEUE_NOTIFICATION: str

    # AI — Gemini
    VERTEX_AI_LOCATION: str = "us-central1"
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Telegram
    TELEGRAM_API_ID: str
    TELEGRAM_API_HASH: str
    TELEGRAM_SESSION_STRING: str
    TELEGRAM_CHANNEL_ID: int
    TELEGRAM_NOTIFY_CHAT_ID: int

    # Gmail
    GMAIL_OAUTH_CLIENT_ID: str
    GMAIL_OAUTH_CLIENT_SECRET: str
    GMAIL_OAUTH_REFRESH_TOKEN: str
    GMAIL_SENDER_ADDRESS: str

    # Application Behavior Tuning
    RELEVANCE_THRESHOLD: int = 65
    MAX_PORTAL_APPS_PER_DAY: int = 5
    JOB_EXPIRY_DAYS: int = 14
    STALE_APPLICATION_WINDOW_MINUTES: int = 90
    CLEANUP_RUN_INTERVAL_MINUTES: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
