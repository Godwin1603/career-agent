"""
Playwright Portal Strategy.
"""

import logging
import time

from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from src.core.config import settings
from src.workers.dto import WorkerContext, WorkerOutcome, WorkerResult
from src.workers.playwright.browser import BrowserManager
from src.workers.playwright.dto import PortalContext
from src.workers.playwright.helpers.locators import get_field_locator
from src.workers.playwright.helpers.screenshots import capture_screenshot
from src.workers.playwright.helpers.upload import upload_resume
from src.workers.strategies import BaseStrategy

logger = logging.getLogger(__name__)


class PlaywrightPortalStrategy(BaseStrategy):
    """
    Playwright-based strategy for portal applications.
    """

    def __init__(self, browser_manager: BrowserManager | None = None):
        self.browser_manager = browser_manager or BrowserManager()

    async def execute(self, context: WorkerContext) -> WorkerResult:
        start_time = time.monotonic()

        # Safely extract job url and portal name
        job_url = getattr(context.job, "url", "https://example.com/job")
        portal_name = getattr(context.job, "portal_name", "default")
        job_id = getattr(context.job, "id", "unknown")

        portal_ctx = PortalContext(
            job_url=job_url,
            first_name="Candidate",
            last_name="Name",
            email="candidate@example.com",
            # We map context.resume.content (assuming it points to a file/text)
            resume_path=context.resume.content if context.resume else None,
        )

        session = await self.browser_manager.create_session(profile_id=portal_name)
        failure_shot = None

        try:
            page = session.page

            # 1. Load portal URL
            await page.goto(portal_ctx.job_url, timeout=settings.BROWSER_TIMEOUT_MS)

            # 2. Wait for page
            await page.wait_for_load_state("domcontentloaded")

            # 3. Validate page
            page_title = await page.title()
            if "404" in page_title or "closed" in page_title.lower():
                raise ValueError("application closed")

            # 4. Login if required (No-op in this generic phase)

            # 5. Navigate to application page (Assume already on it)

            # 6. Upload resume
            if portal_ctx.resume_path:
                try:
                    await upload_resume(page, portal_ctx.resume_path)
                except Exception as e:
                    raise ValueError(f"resume upload failed: {e}")

            # 7. Fill deterministic fields
            fields_to_fill = {
                "First Name": portal_ctx.first_name,
                "Last Name": portal_ctx.last_name,
                "Email": portal_ctx.email,
            }

            for field_name, field_value in fields_to_fill.items():
                loc = get_field_locator(page, field_name)
                # Attempt to fill if it exists; for strictness, we could fail if missing
                if await loc.count() > 0:
                    await loc.fill(field_value)

            # 8. Screenshot before submit
            pre_shot = await capture_screenshot(page, f"job_{job_id}_before")

            # 9. Submit application
            submit_btn = page.get_by_role("button", name="Submit", exact=False)
            if await submit_btn.count() > 0:
                await submit_btn.first.click()
            else:
                raise ValueError("required field missing: Submit button")

            # 10. Screenshot after submit
            post_shot = await capture_screenshot(page, f"job_{job_id}_after")

            elapsed = int((time.monotonic() - start_time) * 1000)
            return WorkerResult(
                outcome=WorkerOutcome.success,
                metadata={
                    "screenshot_path": post_shot,
                    "elapsed_ms": elapsed,
                    "submission_reference": "playwright_submitted",
                },
            )

        except PlaywrightTimeoutError as e:
            # Retryable: navigation timeout, page load timeout
            failure_shot = await capture_screenshot(page, f"job_{job_id}_failure")
            return WorkerResult(
                outcome=WorkerOutcome.retryable_failure,
                error_message=f"navigation timeout: {e}",
                metadata={"screenshot_path": failure_shot},
            )
        except PlaywrightError as e:
            # Retryable: temporary network failure, browser crash
            err_str = str(e).lower()
            failure_shot = await capture_screenshot(page, f"job_{job_id}_failure")
            if "net::" in err_str or "target closed" in err_str or "crash" in err_str:
                return WorkerResult(
                    outcome=WorkerOutcome.retryable_failure,
                    error_message=f"browser crash or network failure: {e}",
                    metadata={"screenshot_path": failure_shot},
                )
            # Otherwise treat as Terminal: unsupported portal, etc.
            return WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=f"unsupported portal or execution error: {e}",
                metadata={"screenshot_path": failure_shot},
            )
        except Exception as e:
            # Terminal: required field missing, application closed, resume upload failed
            failure_shot = await capture_screenshot(page, f"job_{job_id}_failure")
            return WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=str(e),
                metadata={"screenshot_path": failure_shot},
            )
        finally:
            await self.browser_manager.close_session(session)
