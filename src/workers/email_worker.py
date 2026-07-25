"""
Email application worker.

Orchestrates the lifecycle of an email-based job application.
Delegates actual email sending to the injected EmailStrategy.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import ApplicationStrategy
from src.workers.base import BaseApplicationWorker
from src.workers.strategies import BaseStrategy, EmailStrategy

logger = logging.getLogger(__name__)


class EmailWorker(BaseApplicationWorker):
    """
    Worker for email-based job applications.
    Uses EmailStrategy (Gmail API) for actual submission.
    """

    def __init__(
        self,
        session: AsyncSession,
        strategy: EmailStrategy | None = None,
    ) -> None:
        super().__init__(session)
        self._strategy = strategy or EmailStrategy()

    @property
    def strategy_type(self) -> ApplicationStrategy:
        return ApplicationStrategy.email

    def _get_strategy(self) -> BaseStrategy:
        return self._strategy
