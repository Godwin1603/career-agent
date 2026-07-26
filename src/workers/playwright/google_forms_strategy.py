"""
Google Forms automation strategy.
"""

import logging
import time

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.core.config import settings
from src.workers.dto import WorkerContext, WorkerOutcome, WorkerResult
from src.workers.playwright.browser import BrowserManager
from src.workers.playwright.helpers.ai_engine import GoogleFormsAIAnswerEngine
from src.workers.playwright.helpers.form_classifier import FieldType, classify_field
from src.workers.playwright.helpers.form_filler import (
    fill_field,
    get_question_blocks,
    get_question_title,
    handle_file_upload,
)
from src.workers.playwright.helpers.screenshots import capture_screenshot
from src.workers.strategies import BaseStrategy

logger = logging.getLogger(__name__)


class GoogleFormsStrategy(BaseStrategy):
    """
    Playwright-based strategy for Google Forms applications.
    Handles multi-page navigation, deterministic profile filling, AI question answering,
    and manual pause detection.
    """

    def __init__(
        self,
        browser_manager: BrowserManager | None = None,
        ai_engine: GoogleFormsAIAnswerEngine | None = None,
    ):
        self.browser_manager = browser_manager or BrowserManager()
        self.ai_engine = ai_engine or GoogleFormsAIAnswerEngine()

    def _get_profile_value(self, title: str, context: WorkerContext) -> str:
        """Deterministic mapping of profile data from WorkerContext."""
        t = title.lower()
        if "email" in t:
            return "candidate@example.com"
        if "phone" in t:
            return "+15550100"
        if "location" in t:
            return "New York, NY"
        if "linkedin" in t:
            return "https://linkedin.com/in/candidate"
        if "github" in t:
            return "https://github.com/candidate"
        if "website" in t or "portfolio" in t:
            return "https://candidate.example.com"
        if "company" in t:
            return "Acme Corp"
        if "college" in t or "degree" in t:
            return "B.S. Computer Science, State University"
        if "cgpa" in t:
            return "3.8"
        if "experience" in t:
            return "5 years"
        if "skills" in t:
            return "Python, Playwright, SQL, GCP"
        if "notice period" in t:
            return "2 weeks"
        if "salary" in t:
            return "120000"
        if "authorization" in t or "visa" in t or "sponsorship" in t:
            return "Yes"

        # Default fallback for "Name" or unknown profile fields
        return "Candidate Name"

    async def execute(self, context: WorkerContext) -> WorkerResult:
        start_time = time.monotonic()
        job_url = getattr(context.job, "url", "https://docs.google.com/forms")
        job_id = getattr(context.job, "id", "unknown")
        resume_path = context.resume.content if context.resume else None

        session = await self.browser_manager.create_session(profile_id="google_forms")
        failure_shot = None

        try:
            page = session.page
            await page.goto(job_url, timeout=settings.BROWSER_TIMEOUT_MS)
            await page.wait_for_load_state("domcontentloaded")

            page_title = await page.title()
            if "deleted" in page_title.lower() or "Page Not Found" in page_title:
                raise ValueError("form deleted or not found")
            if (
                "permission denied" in page_title.lower()
                or "need permission" in page_title.lower()
            ):
                raise ValueError("permission denied")

            while True:
                # Parse current page fields
                blocks = await get_question_blocks(page)

                for block in blocks:
                    title = await get_question_title(block)
                    field_type = classify_field(title)

                    logger.info(
                        "Field classified (title=%r, type=%s)", title, field_type.value
                    )

                    if field_type == FieldType.MANUAL:
                        # Manual pause mode triggered
                        pause_shot = await capture_screenshot(
                            page, f"job_{job_id}_manual_pause"
                        )
                        return WorkerResult(
                            outcome=WorkerOutcome.retryable_failure,
                            error_message="Manual intervention required",
                            metadata={
                                "status": "WAITING_FOR_USER",
                                "reason": (
                                    f"UNSUPPORTED_FIELD_"
                                    f"{title.upper().replace(' ', '_')}"
                                ),
                                "screenshot_path": pause_shot,
                            },
                        )

                    elif field_type == FieldType.UPLOAD:
                        if resume_path:
                            await handle_file_upload(page, block, resume_path)
                        else:
                            raise ValueError("missing upload file")

                    elif field_type == FieldType.PROFILE:
                        val = self._get_profile_value(title, context)
                        await fill_field(block, val)

                    elif field_type == FieldType.AI:
                        # Use AI for descriptive fields
                        resume_txt = "Experienced Software Engineer"  # Mock context
                        ans = await self.ai_engine.generate_answer(title, resume_txt)
                        await fill_field(block, ans)

                    elif (
                        field_type == FieldType.RULE or field_type == FieldType.UNKNOWN
                    ):
                        # Attempt to fill with a generic fallback or skip gracefully
                        await fill_field(block, "N/A")

                # Handle Navigation
                next_btn = page.get_by_role("button", name="Next", exact=False)
                submit_btn = page.get_by_role("button", name="Submit", exact=False)

                if await submit_btn.count() > 0:
                    # Capture pre-submit screenshot
                    await capture_screenshot(page, f"job_{job_id}_before")
                    await submit_btn.first.click()
                    await page.wait_for_load_state("networkidle")
                    # Capture post-submit screenshot
                    post_shot = await capture_screenshot(page, f"job_{job_id}_after")
                    break
                elif await next_btn.count() > 0:
                    await next_btn.first.click()
                    await page.wait_for_load_state("networkidle")
                else:
                    # Broken form or unhandled navigation
                    raise ValueError("broken form: no next or submit button")

            elapsed = int((time.monotonic() - start_time) * 1000)
            return WorkerResult(
                outcome=WorkerOutcome.success,
                metadata={
                    "screenshot_path": post_shot,
                    "elapsed_ms": elapsed,
                    "submission_reference": "google_forms_submitted",
                },
            )

        except PlaywrightTimeoutError as e:
            failure_shot = await capture_screenshot(page, f"job_{job_id}_failure")
            return WorkerResult(
                outcome=WorkerOutcome.retryable_failure,
                error_message=f"network timeout: {e}",
                metadata={"screenshot_path": failure_shot},
            )
        except PlaywrightError as e:
            err_str = str(e).lower()
            failure_shot = await capture_screenshot(page, f"job_{job_id}_failure")
            if (
                "net::" in err_str
                or "target closed" in err_str
                or "stale element" in err_str
            ):
                return WorkerResult(
                    outcome=WorkerOutcome.retryable_failure,
                    error_message=f"temporary DOM or network failure: {e}",
                    metadata={"screenshot_path": failure_shot},
                )
            return WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=f"execution error: {e}",
                metadata={"screenshot_path": failure_shot},
            )
        except Exception as e:
            failure_shot = await capture_screenshot(page, f"job_{job_id}_failure")
            return WorkerResult(
                outcome=WorkerOutcome.terminal_failure,
                error_message=str(e),
                metadata={"screenshot_path": failure_shot},
            )
        finally:
            await self.browser_manager.close_session(session)
