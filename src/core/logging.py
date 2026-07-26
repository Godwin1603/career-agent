"""
Structured logging for career-agent.

Provides two modes:
  - ``plain`` (default): human-readable format suitable for local development.
  - ``json``: JSON-structured format compatible with Google Cloud Logging.

Mode is selected by the ``LOG_FORMAT`` environment variable (default: ``plain``).
Log level is controlled by the ``LOG_LEVEL`` environment variable (default: ``INFO``).

SECURITY
--------
The logging pipeline NEVER captures: passwords, OTP codes, OAuth tokens,
cookies, session data, verification URLs, or Secret Manager values.
Any handler that receives such data in a message MUST NOT forward it.
"""

import json
import logging
import sys
from typing import Literal


class _JsonFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects compatible with
    Google Cloud Logging structured logs.

    Fields emitted:
      timestamp  — ISO-8601 UTC
      severity   — GCP severity label (DEBUG/INFO/WARNING/ERROR/CRITICAL)
      logger     — logger name
      message    — formatted message
      exc_info   — exception string (omitted when absent)
    """

    _GCP_SEVERITY = {
        "DEBUG": "DEBUG",
        "INFO": "INFO",
        "WARNING": "WARNING",
        "ERROR": "ERROR",
        "CRITICAL": "CRITICAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "severity": self._GCP_SEVERITY.get(record.levelname, record.levelname),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # Include any extra fields added by callers (e.g. job_id, strategy)
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "taskName",
            }:
                payload[key] = value
        return json.dumps(payload, default=str)


def setup_logging(
    log_level: int = logging.INFO,
    format_mode: Literal["plain", "json"] = "plain",
) -> None:
    """
    Configure root logger.

    Args:
        log_level: Python logging level (e.g. ``logging.INFO``).
        format_mode: ``"plain"`` for human-readable, ``"json"`` for GCP-structured.
    """
    import os

    # Override from environment if set
    env_level = os.getenv("LOG_LEVEL", "").upper()
    if env_level and hasattr(logging, env_level):
        log_level = getattr(logging, env_level)

    env_format = os.getenv("LOG_FORMAT", "plain").lower()
    if env_format in ("json", "structured"):
        format_mode = "json"

    if format_mode == "json":
        formatter: logging.Formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-8s %(name)s — %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove any existing handlers before adding ours to avoid duplication
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress verbose third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)
    logging.getLogger("playwright").setLevel(logging.WARNING)
