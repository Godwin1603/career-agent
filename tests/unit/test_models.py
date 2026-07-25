"""
Unit tests for Phase 2 database models.

These tests verify model structure, relationships, enum mappings, constraints,
and index definitions using SQLAlchemy's introspection API — no live database
is required.
"""

import pytest
from sqlalchemy import inspect, text

import src.core.model_registry  # noqa: F401 — ensures all models register on Base.metadata
from src.applications.models import Application, ApplicationEvent
from src.core.database import Base
from src.core.enums import (
    ApplicationStatus,
    ApplicationStrategy,
    NotificationDeliveryStatus,
    NotificationType,
    RawMessageStatus,
    ResumeLabel,
    TaskStatus,
    TaskType,
)
from src.core.task_log import TaskLog
from src.jobs.models import Job, JobRawMessage
from src.notifications.models import Notification
from src.portals.models import PortalConfig
from src.resumes.models import ApplicationResume, Resume

# ---------------------------------------------------------------------------
# Model import tests
# ---------------------------------------------------------------------------


def test_all_models_importable():
    """All domain model classes can be imported without error."""
    assert Job is not None
    assert JobRawMessage is not None
    assert Application is not None
    assert ApplicationEvent is not None
    assert Resume is not None
    assert ApplicationResume is not None
    assert Notification is not None
    assert PortalConfig is not None
    assert TaskLog is not None


# ---------------------------------------------------------------------------
# Metadata registration tests
# ---------------------------------------------------------------------------


def test_all_tables_registered_on_metadata():
    """All documented tables are registered on Base.metadata."""
    expected_tables = {
        "job_raw_messages",
        "jobs",
        "applications",
        "application_events",
        "resumes",
        "application_resumes",
        "notifications",
        "portal_configs",
        "task_log",
    }
    registered = set(Base.metadata.tables.keys())
    assert expected_tables == registered, (
        f"Missing tables: {expected_tables - registered}\n"
        f"Extra tables: {registered - expected_tables}"
    )


# ---------------------------------------------------------------------------
# Column presence tests
# ---------------------------------------------------------------------------


def _columns(table_name: str) -> set[str]:
    return {c.name for c in Base.metadata.tables[table_name].columns}


def test_jobs_columns():
    cols = _columns("jobs")
    assert {
        "id",
        "raw_message_id",
        "company_name",
        "role_title",
        "location",
        "is_remote",
        "application_url",
        "email_address",
        "google_form_url",
        "salary_range",
        "relevance_score",
        "detected_portal",
        "status",
        "created_at",
        "updated_at",
        "expires_at",
    } <= cols


def test_job_raw_messages_columns():
    cols = _columns("job_raw_messages")
    assert {
        "id",
        "telegram_message_id",
        "channel_id",
        "raw_text",
        "status",
        "created_at",
        "updated_at",
    } <= cols


def test_applications_columns():
    cols = _columns("applications")
    assert {
        "id",
        "job_id",
        "strategy",
        "status",
        "attempt_count",
        "last_error",
        "applied_at",
        "created_at",
        "updated_at",
    } <= cols


def test_application_events_columns():
    cols = _columns("application_events")
    assert {"id", "application_id", "event_type", "event_payload", "created_at"} <= cols


def test_resumes_columns():
    cols = _columns("resumes")
    assert {
        "id",
        "label",
        "job_id",
        "gcs_path",
        "content_hash",
        "created_at",
        "updated_at",
    } <= cols


def test_application_resumes_columns():
    cols = _columns("application_resumes")
    assert {"application_id", "resume_id", "created_at"} <= cols


def test_notifications_columns():
    cols = _columns("notifications")
    assert {
        "id",
        "job_id",
        "application_id",
        "notification_type",
        "message_content",
        "delivery_status",
        "created_at",
        "updated_at",
    } <= cols


def test_portal_configs_columns():
    cols = _columns("portal_configs")
    assert {
        "id",
        "portal_name",
        "portal_base_url",
        "config_payload",
        "is_enabled",
        "created_at",
        "updated_at",
    } <= cols


def test_task_log_columns():
    cols = _columns("task_log")
    assert {
        "id",
        "cloud_task_name",
        "task_type",
        "entity_id",
        "status",
        "error",
        "created_at",
        "completed_at",
    } <= cols


# ---------------------------------------------------------------------------
# Foreign key tests
# ---------------------------------------------------------------------------


def _fk_targets(table_name: str) -> set[str]:
    table = Base.metadata.tables[table_name]
    return {fk.target_fullname for fk in table.foreign_keys}


def test_jobs_fk_to_job_raw_messages():
    assert "job_raw_messages.id" in _fk_targets("jobs")


def test_applications_fk_to_jobs():
    assert "jobs.id" in _fk_targets("applications")


def test_application_events_fk_to_applications():
    assert "applications.id" in _fk_targets("application_events")


def test_resumes_fk_to_jobs():
    assert "jobs.id" in _fk_targets("resumes")


def test_application_resumes_fks():
    targets = _fk_targets("application_resumes")
    assert "applications.id" in targets
    assert "resumes.id" in targets


def test_notifications_fks():
    targets = _fk_targets("notifications")
    assert "jobs.id" in targets
    assert "applications.id" in targets


# ---------------------------------------------------------------------------
# Nullable constraint tests
# ---------------------------------------------------------------------------


def _nullable_map(table_name: str) -> dict[str, bool]:
    return {c.name: c.nullable for c in Base.metadata.tables[table_name].columns}


def test_notifications_job_id_nullable():
    assert _nullable_map("notifications")["job_id"] is True


def test_notifications_application_id_nullable():
    assert _nullable_map("notifications")["application_id"] is True


def test_resumes_job_id_nullable():
    assert _nullable_map("resumes")["job_id"] is True


def test_jobs_raw_message_id_nullable():
    assert _nullable_map("jobs")["raw_message_id"] is True


def test_applications_last_error_nullable():
    assert _nullable_map("applications")["last_error"] is True


def test_applications_applied_at_nullable():
    assert _nullable_map("applications")["applied_at"] is True


# ---------------------------------------------------------------------------
# Unique constraint tests
# ---------------------------------------------------------------------------


def _unique_constraint_columns(table_name: str) -> list[frozenset[str]]:
    table = Base.metadata.tables[table_name]
    result = []
    for constraint in table.constraints:
        from sqlalchemy import UniqueConstraint

        if isinstance(constraint, UniqueConstraint):
            result.append(frozenset(c.name for c in constraint.columns))
    return result


def test_applications_unique_job_strategy():
    uqs = _unique_constraint_columns("applications")
    assert frozenset({"job_id", "strategy"}) in uqs


def test_job_raw_messages_unique_telegram_channel():
    uqs = _unique_constraint_columns("job_raw_messages")
    assert frozenset({"telegram_message_id", "channel_id"}) in uqs


def test_portal_configs_unique_portal_name():
    uqs = _unique_constraint_columns("portal_configs")
    assert frozenset({"portal_name"}) in uqs


# ---------------------------------------------------------------------------
# Primary key tests
# ---------------------------------------------------------------------------


def _pk_columns(table_name: str) -> set[str]:
    return {c.name for c in Base.metadata.tables[table_name].primary_key}


def test_application_resumes_composite_pk():
    pks = _pk_columns("application_resumes")
    assert pks == {"application_id", "resume_id"}


def test_jobs_pk():
    assert _pk_columns("jobs") == {"id"}


def test_applications_pk():
    assert _pk_columns("applications") == {"id"}


# ---------------------------------------------------------------------------
# Enum mapping tests
# ---------------------------------------------------------------------------


def test_application_status_values():
    values = {e.value for e in ApplicationStatus}
    assert values == {
        "pending",
        "in_progress",
        "success",
        "failed",
        "skipped",
        "permanently_failed",
    }


def test_application_strategy_values():
    values = {e.value for e in ApplicationStrategy}
    assert values == {"portal", "form", "email"}


def test_resume_label_values():
    values = {e.value for e in ResumeLabel}
    assert values == {"base", "tailored"}


def test_notification_type_values():
    values = {e.value for e in NotificationType}
    assert values == {
        "new_job_found",
        "job_skipped",
        "application_submitted",
        "application_failed_retry",
        "application_permanently_failed",
    }


def test_notification_delivery_status_values():
    values = {e.value for e in NotificationDeliveryStatus}
    assert values == {"pending", "sent", "failed"}


def test_raw_message_status_values():
    values = {e.value for e in RawMessageStatus}
    assert values == {"pending", "processed", "failed"}


def test_task_type_values():
    values = {e.value for e in TaskType}
    assert values == {
        "job_enrichment",
        "portal_application",
        "form_application",
        "email_application",
        "notification",
    }


def test_task_status_values():
    values = {e.value for e in TaskStatus}
    assert values == {"pending", "running", "success", "failed"}


# ---------------------------------------------------------------------------
# SQLAlchemy relationship tests
# ---------------------------------------------------------------------------


def test_job_has_applications_relationship():
    mapper = inspect(Job)
    assert "applications" in {r.key for r in mapper.relationships}


def test_job_has_resumes_relationship():
    mapper = inspect(Job)
    assert "resumes" in {r.key for r in mapper.relationships}


def test_job_has_notifications_relationship():
    mapper = inspect(Job)
    assert "notifications" in {r.key for r in mapper.relationships}


def test_job_has_raw_message_relationship():
    mapper = inspect(Job)
    assert "raw_message" in {r.key for r in mapper.relationships}


def test_application_has_events_relationship():
    mapper = inspect(Application)
    assert "events" in {r.key for r in mapper.relationships}


def test_application_has_notifications_relationship():
    mapper = inspect(Application)
    assert "notifications" in {r.key for r in mapper.relationships}


def test_application_has_resumes_relationship():
    mapper = inspect(Application)
    assert "application_resumes" in {r.key for r in mapper.relationships}


def test_resume_has_application_resumes_relationship():
    mapper = inspect(Resume)
    assert "application_resumes" in {r.key for r in mapper.relationships}


def test_notification_has_job_relationship():
    mapper = inspect(Notification)
    assert "job" in {r.key for r in mapper.relationships}


def test_notification_has_application_relationship():
    mapper = inspect(Notification)
    assert "application" in {r.key for r in mapper.relationships}


# ---------------------------------------------------------------------------
# Live database schema tests (require DB via docker-compose)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alembic_upgrade_creates_all_tables(db_engine):
    """Verify all expected tables exist after alembic upgrade head."""
    expected = {
        "job_raw_messages",
        "jobs",
        "applications",
        "application_events",
        "resumes",
        "application_resumes",
        "notifications",
        "portal_configs",
        "task_log",
    }
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables " "WHERE schemaname = 'public'")
        )
        actual = {row[0] for row in result}
    assert expected <= actual, f"Missing tables: {expected - actual}"


@pytest.mark.asyncio
async def test_alembic_downgrade_removes_all_tables(db_engine_after_downgrade):
    """Verify all application tables are removed after alembic downgrade base."""
    app_tables = {
        "job_raw_messages",
        "jobs",
        "applications",
        "application_events",
        "resumes",
        "application_resumes",
        "notifications",
        "portal_configs",
        "task_log",
    }
    async with db_engine_after_downgrade.connect() as conn:
        result = await conn.execute(
            text("SELECT tablename FROM pg_tables " "WHERE schemaname = 'public'")
        )
        remaining = {row[0] for row in result}
    assert app_tables.isdisjoint(
        remaining
    ), f"Tables still present after downgrade: {app_tables & remaining}"
