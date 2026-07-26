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
    Delegates to GmailEmailStrategy (Phase 10).

    The GmailClient is built lazily from settings on first call.
    Workers that need a custom GmailClient should construct
    GmailEmailStrategy directly and inject it.
    """

    async def execute(self, context: WorkerContext) -> WorkerResult:
        from src.core.config import settings
        from src.integrations.gmail.client import GmailClient
        from src.integrations.gmail.email_strategy import GmailEmailStrategy

        client = GmailClient(
            client_id=settings.GMAIL_OAUTH_CLIENT_ID,
            client_secret=settings.GMAIL_OAUTH_CLIENT_SECRET,
            refresh_token=settings.GMAIL_OAUTH_REFRESH_TOKEN,
            sender_address=settings.GMAIL_SENDER_ADDRESS,
        )
        strategy = GmailEmailStrategy(gmail_client=client)
        return await strategy.execute(context)
