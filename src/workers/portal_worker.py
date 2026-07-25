"""
Portal application worker.

Orchestrates the lifecycle of a portal-based job application.
Delegates actual browser automation to the injected PortalStrategy.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import ApplicationStrategy
from src.workers.base import BaseApplicationWorker
from src.workers.strategies import BaseStrategy, PortalStrategy

logger = logging.getLogger(__name__)


class PortalWorker(BaseApplicationWorker):
    """
    Worker for portal-based job applications.
    Uses PortalStrategy (Playwright) for actual submission.
    """

    def __init__(
        self,
        session: AsyncSession,
        strategy: PortalStrategy | None = None,
    ) -> None:
        super().__init__(session)
        self._strategy = strategy or PortalStrategy()

    @property
    def strategy_type(self) -> ApplicationStrategy:
        return ApplicationStrategy.portal

    def _get_strategy(self) -> BaseStrategy:
        return self._strategy
