"""
Strategy abstractions for application workers.

Each strategy defines a single async execute() method.
The concrete implementations (Playwright, Gmail API, etc.) are deferred
to future phases. These abstractions allow workers to be fully tested
against mock strategies.
"""

from abc import ABC, abstractmethod

from src.workers.dto import WorkerContext, WorkerResult


class BaseStrategy(ABC):
    """
    Abstract base for all application strategies.
    Each strategy accepts a WorkerContext and returns a WorkerResult.
    """

    @abstractmethod
    async def execute(self, context: WorkerContext) -> WorkerResult:
        """
        Execute the strategy for the given context.

        Args:
            context: Contains the Application, Job, and Resume.

        Returns:
            WorkerResult indicating success, retryable failure, or terminal failure.
        """
        ...


class PortalStrategy(BaseStrategy):
    """
    Abstraction for portal-based job applications (e.g. Workday, Lever).
    Now uses Playwright for browser automation.
    """

    async def execute(self, context: WorkerContext) -> WorkerResult:
        from src.workers.playwright.strategy import PlaywrightPortalStrategy

        strategy = PlaywrightPortalStrategy()
        return await strategy.execute(context)


class FormStrategy(BaseStrategy):
    """
    Abstraction for Google Form-based job applications.
    Concrete implementation will automate form submission.
    """

    async def execute(self, context: WorkerContext) -> WorkerResult:
        """Mock implementation — to be replaced with form automation."""
        raise NotImplementedError(
            "FormStrategy.execute() is not yet implemented. "
            "Awaiting Google Forms integration in a future phase."
        )


class EmailStrategy(BaseStrategy):
    """
    Abstraction for email-based job applications.
    Concrete implementation will use the Gmail API.
    """

    async def execute(self, context: WorkerContext) -> WorkerResult:
        """Mock implementation — to be replaced with Gmail API integration."""
        raise NotImplementedError(
            "EmailStrategy.execute() is not yet implemented. "
            "Awaiting Gmail API integration in a future phase."
        )
