"""
Google Form application worker.

Orchestrates the lifecycle of a Google Form-based job application.
Delegates actual form submission to the injected FormStrategy.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.enums import ApplicationStrategy
from src.workers.base import BaseApplicationWorker
from src.workers.strategies import BaseStrategy, FormStrategy

logger = logging.getLogger(__name__)


class GoogleFormWorker(BaseApplicationWorker):
    """
    Worker for Google Form-based job applications.
    Uses FormStrategy for actual submission.
    """

    def __init__(
        self,
        session: AsyncSession,
        strategy: FormStrategy | None = None,
    ) -> None:
        super().__init__(session)
        self._strategy = strategy or FormStrategy()

    @property
    def strategy_type(self) -> ApplicationStrategy:
        return ApplicationStrategy.form

    def _get_strategy(self) -> BaseStrategy:
        return self._strategy
