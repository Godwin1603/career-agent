"""
Browser and session management for Playwright strategies.
"""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

logger = logging.getLogger(__name__)


class BrowserSession:
    """
    Encapsulates an active Playwright browser context and main page.
    """

    def __init__(
        self, context: BrowserContext, page: Page, profile_id: str = "default"
    ):
        self.context = context
        self.page = page
        self.profile_id = profile_id


class BrowserManager:
    """
    Manages Playwright browser lifecycle.
    Supports persistent profiles and graceful shutdown.
    """

    def __init__(self, user_data_dir: str = ".browser_profiles"):
        self.user_data_dir = Path(user_data_dir)
        self.user_data_dir.mkdir(parents=True, exist_ok=True)
        self._playwright: Optional[Playwright] = None
        self._profile_locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, profile_id: str) -> asyncio.Lock:
        if profile_id not in self._profile_locks:
            self._profile_locks[profile_id] = asyncio.Lock()
        return self._profile_locks[profile_id]

    async def start(self) -> None:
        """Start the Playwright driver."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def create_session(
        self, profile_id: str = "default", headless: bool = True
    ) -> BrowserSession:
        """
        Launch a persistent browser context and return the session.
        This automatically loads the browser profile if it exists,
        and persists it during the session.
        """
        lock = self._get_lock(profile_id)
        await lock.acquire()

        try:
            if self._playwright is None:
                await self.start()

            profile_path = self.user_data_dir / profile_id

            context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1280, "height": 720},
            )

            # A persistent context always comes with at least one default page
            if context.pages:
                page = context.pages[0]
            else:
                page = await context.new_page()

            return BrowserSession(context=context, page=page, profile_id=profile_id)
        except Exception:
            if lock.locked():
                lock.release()
            raise

    async def close_session(self, session: BrowserSession) -> None:
        """Gracefully close a browser session."""
        try:
            await session.context.close()
        except Exception as e:
            logger.warning(f"Error closing browser session: {e}")
        finally:
            if hasattr(session, "profile_id"):
                lock = self._get_lock(session.profile_id)
                if lock.locked():
                    lock.release()

    async def shutdown(self) -> None:
        """Shutdown Playwright completely."""
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None
