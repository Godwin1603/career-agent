"""implement phase 2 database models

Revision ID: 0001
Revises:
Create Date: 2026-07-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Enum types -----------------------------------------------------------
    rawmessagestatus = postgresql.ENUM(
        "pending", "processed", "failed", name="rawmessagestatus", create_type=False
    )
    rawmessagestatus.create(op.get_bind(), checkfirst=True)

    jobstatus = postgresql.ENUM(
        "pending", "enriched", "skipped", "expired", name="jobstatus", create_type=False
    )
    jobstatus.create(op.get_bind(), checkfirst=True)

    applicationstrategy = postgresql.ENUM(
        "portal", "form", "email", name="applicationstrategy", create_type=False
    )
    applicationstrategy.create(op.get_bind(), checkfirst=True)

    applicationstatus = postgresql.ENUM(
        "pending",
        "in_progress",
        "success",
        "failed",
        "skipped",
        "permanently_failed",
        name="applicationstatus",
        create_type=False,
    )
    applicationstatus.create(op.get_bind(), checkfirst=True)

    resumelabel = postgresql.ENUM(
        "base", "tailored", name="resumelabel", create_type=False
    )
    resumelabel.create(op.get_bind(), checkfirst=True)

    notificationtype = postgresql.ENUM(
        "new_job_found",
        "job_skipped",
        "application_submitted",
        "application_failed_retry",
        "application_permanently_failed",
        name="notificationtype",
        create_type=False,
    )
    notificationtype.create(op.get_bind(), checkfirst=True)

    notificationdeliverystatus = postgresql.ENUM(
        "pending",
        "sent",
        "failed",
        name="notificationdeliverystatus",
        create_type=False,
    )
    notificationdeliverystatus.create(op.get_bind(), checkfirst=True)

    tasktype = postgresql.ENUM(
        "job_enrichment",
        "portal_application",
        "form_application",
        "email_application",
        "notification",
        name="tasktype",
        create_type=False,
    )
    tasktype.create(op.get_bind(), checkfirst=True)

    taskstatus = postgresql.ENUM(
        "pending", "running", "success", "failed", name="taskstatus", create_type=False
    )
    taskstatus.create(op.get_bind(), checkfirst=True)

    # --- job_raw_messages -----------------------------------------------------
    op.create_table(
        "job_raw_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processed",
                "failed",
                name="rawmessagestatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "telegram_message_id",
            "channel_id",
            name="uq_job_raw_messages_telegram_message_channel",
        ),
    )
    op.create_index(
        "ix_job_raw_messages_channel_id", "job_raw_messages", ["channel_id"]
    )
    op.create_index(
        "ix_job_raw_messages_created_at", "job_raw_messages", ["created_at"]
    )
    op.create_index("ix_job_raw_messages_status", "job_raw_messages", ["status"])
    op.create_index(
        "ix_job_raw_messages_telegram_message_id",
        "job_raw_messages",
        ["telegram_message_id"],
    )

    # --- jobs -----------------------------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column("role_title", sa.String(255), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("is_remote", sa.Boolean(), nullable=True),
        sa.Column("application_url", sa.Text(), nullable=True),
        sa.Column("email_address", sa.String(320), nullable=True),
        sa.Column("google_form_url", sa.Text(), nullable=True),
        sa.Column("salary_range", sa.String(255), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("detected_portal", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "enriched",
                "skipped",
                "expired",
                name="jobstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["raw_message_id"],
            ["job_raw_messages.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_index("ix_jobs_detected_portal", "jobs", ["detected_portal"])
    op.create_index("ix_jobs_expires_at", "jobs", ["expires_at"])
    op.create_index("ix_jobs_raw_message_id", "jobs", ["raw_message_id"])
    op.create_index("ix_jobs_relevance_score", "jobs", ["relevance_score"])
    op.create_index("ix_jobs_status", "jobs", ["status"])

    # --- applications ---------------------------------------------------------
    op.create_table(
        "applications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "strategy",
            sa.Enum(
                "portal", "form", "email", name="applicationstrategy", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in_progress",
                "success",
                "failed",
                "skipped",
                "permanently_failed",
                name="applicationstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "strategy", name="uq_applications_job_strategy"),
    )
    op.create_index("ix_applications_job_id", "applications", ["job_id"])
    op.create_index("ix_applications_status", "applications", ["status"])
    op.create_index("ix_applications_strategy", "applications", ["strategy"])
    op.create_index("ix_applications_updated_at", "applications", ["updated_at"])

    # --- application_events ---------------------------------------------------
    op.create_table(
        "application_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "event_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_events_application_id",
        "application_events",
        ["application_id"],
    )
    op.create_index(
        "ix_application_events_created_at", "application_events", ["created_at"]
    )
    op.create_index(
        "ix_application_events_event_type", "application_events", ["event_type"]
    )

    # --- resumes --------------------------------------------------------------
    op.create_table(
        "resumes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "label",
            sa.Enum("base", "tailored", name="resumelabel", create_type=False),
            nullable=False,
        ),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("gcs_path", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resumes_content_hash", "resumes", ["content_hash"])
    op.create_index("ix_resumes_job_id", "resumes", ["job_id"])
    op.create_index("ix_resumes_label", "resumes", ["label"])

    # --- application_resumes --------------------------------------------------
    op.create_table(
        "application_resumes",
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resume_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["resume_id"], ["resumes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("application_id", "resume_id"),
    )
    op.create_index(
        "ix_application_resumes_resume_id", "application_resumes", ["resume_id"]
    )

    # --- notifications --------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("application_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "notification_type",
            sa.Enum(
                "new_job_found",
                "job_skipped",
                "application_submitted",
                "application_failed_retry",
                "application_permanently_failed",
                name="notificationtype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("message_content", sa.Text(), nullable=False),
        sa.Column(
            "delivery_status",
            sa.Enum(
                "pending",
                "sent",
                "failed",
                name="notificationdeliverystatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["application_id"], ["applications.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_application_id", "notifications", ["application_id"]
    )
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_index(
        "ix_notifications_delivery_status", "notifications", ["delivery_status"]
    )
    op.create_index("ix_notifications_job_id", "notifications", ["job_id"])
    op.create_index(
        "ix_notifications_notification_type", "notifications", ["notification_type"]
    )

    # --- portal_configs -------------------------------------------------------
    op.create_table(
        "portal_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("portal_name", sa.String(100), nullable=False),
        sa.Column("portal_base_url", sa.Text(), nullable=False),
        sa.Column(
            "config_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("portal_name", name="uq_portal_configs_portal_name"),
    )
    op.create_index("ix_portal_configs_is_enabled", "portal_configs", ["is_enabled"])

    # --- task_log -------------------------------------------------------------
    op.create_table(
        "task_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cloud_task_name", sa.String(500), nullable=False),
        sa.Column(
            "task_type",
            sa.Enum(
                "job_enrichment",
                "portal_application",
                "form_application",
                "email_application",
                "notification",
                name="tasktype",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("entity_id", sa.String(36), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "success",
                "failed",
                name="taskstatus",
                create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cloud_task_name"),
    )
    op.create_index(
        "ix_task_log_cloud_task_name", "task_log", ["cloud_task_name"], unique=True
    )
    op.create_index("ix_task_log_created_at", "task_log", ["created_at"])
    op.create_index(
        "ix_task_log_entity_id_task_type", "task_log", ["entity_id", "task_type"]
    )
    op.create_index("ix_task_log_status", "task_log", ["status"])
    op.create_index("ix_task_log_task_type", "task_log", ["task_type"])
    op.create_index("ix_task_log_entity_id", "task_log", ["entity_id"])


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("task_log")
    op.drop_table("portal_configs")
    op.drop_table("notifications")
    op.drop_table("application_resumes")
    op.drop_table("resumes")
    op.drop_table("application_events")
    op.drop_table("applications")
    op.drop_table("jobs")
    op.drop_table("job_raw_messages")

    # Drop enum types
    op.execute("DROP TYPE IF EXISTS taskstatus")
    op.execute("DROP TYPE IF EXISTS tasktype")
    op.execute("DROP TYPE IF EXISTS notificationdeliverystatus")
    op.execute("DROP TYPE IF EXISTS notificationtype")
    op.execute("DROP TYPE IF EXISTS resumelabel")
    op.execute("DROP TYPE IF EXISTS applicationstatus")
    op.execute("DROP TYPE IF EXISTS applicationstrategy")
    op.execute("DROP TYPE IF EXISTS jobstatus")
    op.execute("DROP TYPE IF EXISTS rawmessagestatus")
