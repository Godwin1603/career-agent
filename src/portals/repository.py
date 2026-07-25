"""
Repository for the portals domain.

Provides persistence operations for PortalConfig records.
No business logic. Session is injected by the caller.
"""

from __future__ import annotations

from sqlalchemy import select

from src.core.exceptions import EntityNotFound
from src.core.repository import BaseRepository
from src.portals.models import PortalConfig


class PortalConfigRepository(BaseRepository[PortalConfig]):
    """Persistence operations for portal configuration records."""

    model = PortalConfig

    async def get_by_name(self, portal_name: str) -> PortalConfig:
        """
        Return the portal config with the given canonical name.
        Raises EntityNotFound if no record exists.

        This is the primary lookup used by the portal worker to load
        the automation hints for a specific portal before form submission.
        """
        stmt = select(PortalConfig).where(PortalConfig.portal_name == portal_name)
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        if row is None:
            raise EntityNotFound(PortalConfig.__name__, portal_name)
        return row

    async def get_by_name_or_none(self, portal_name: str) -> PortalConfig | None:
        """Return the portal config with the given name, or None if not found."""
        stmt = select(PortalConfig).where(PortalConfig.portal_name == portal_name)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_enabled(self) -> list[PortalConfig]:
        """
        Return all enabled portal configs, ordered alphabetically by portal name.
        Used by the portal registry to discover available portals at startup.
        """
        stmt = (
            select(PortalConfig)
            .where(PortalConfig.is_enabled.is_(True))
            .order_by(PortalConfig.portal_name.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_all_portals(self) -> list[PortalConfig]:
        """Return all portal configs (enabled and disabled), ordered alphabetically."""
        stmt = select(PortalConfig).order_by(PortalConfig.portal_name.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def exists_by_name(self, portal_name: str) -> bool:
        """Return True if a portal config with the given name exists."""
        return await self.exists(PortalConfig.portal_name == portal_name)

    async def count_enabled(self) -> int:
        """Return the number of enabled portal configs."""
        return await self.count(PortalConfig.is_enabled.is_(True))
