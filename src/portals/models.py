"""
SQLAlchemy model for the portals domain.

Table:
  - portal_configs: configuration metadata for each supported career portal (permanent)
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.core.database import Base


class PortalConfig(Base):
    """
    Per-portal configuration: field selectors, submission flow hints, bot-detection
    notes, and known limitations. Updated manually as portals change their UI.
    """

    __tablename__ = "portal_configs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Short, canonical name used as the lookup key (e.g. "linkedin", "greenhouse")
    portal_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    portal_base_url: Mapped[str] = mapped_column(Text, nullable=False)
    # Arbitrary JSON config blob: CSS selectors, timing hints, required fields, etc.
    config_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("portal_name", name="uq_portal_configs_portal_name"),
        Index("ix_portal_configs_is_enabled", "is_enabled"),
    )
