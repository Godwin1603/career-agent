"""
Shared enumeration types for the career-agent domain.

All enums are defined here and imported by domain model files.
This avoids duplication and circular imports.
"""

import enum


class JobStatus(str, enum.Enum):
    """Processing lifecycle of a job posting."""

    pending = "pending"
    enriched = "enriched"
    skipped = "skipped"
    expired = "expired"


class ApplicationStrategy(str, enum.Enum):
    """The method used to submit an application."""

    portal = "portal"
    form = "form"
    email = "email"


class ApplicationStatus(str, enum.Enum):
    """Lifecycle state of a single application attempt."""

    pending = "pending"
    in_progress = "in_progress"
    success = "success"
    failed = "failed"
    skipped = "skipped"
    permanently_failed = "permanently_failed"


class ResumeLabel(str, enum.Enum):
    """Whether a resume is a base version or a tailored version."""

    base = "base"
    tailored = "tailored"


class NotificationType(str, enum.Enum):
    """The category of event that triggered a notification."""

    new_job_found = "new_job_found"
    job_skipped = "job_skipped"
    application_submitted = "application_submitted"
    application_failed_retry = "application_failed_retry"
    application_permanently_failed = "application_permanently_failed"


class NotificationDeliveryStatus(str, enum.Enum):
    """Whether the notification was successfully delivered."""

    pending = "pending"
    sent = "sent"
    failed = "failed"


class RawMessageStatus(str, enum.Enum):
    """Processing state of a raw Telegram message."""

    pending = "pending"
    processed = "processed"
    failed = "failed"


class TaskStatus(str, enum.Enum):
    """Execution state of a Cloud Task entry."""

    pending = "pending"
    running = "running"
    success = "success"
    failed = "failed"


class TaskType(str, enum.Enum):
    """The type of work performed by a Cloud Task."""

    job_enrichment = "job_enrichment"
    portal_application = "portal_application"
    form_application = "form_application"
    email_application = "email_application"
    notification = "notification"
