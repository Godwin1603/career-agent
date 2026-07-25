"""
Tests for Phase 8 Playwright Portal Strategy.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.workers.dto import WorkerContext, WorkerOutcome
from src.workers.playwright.browser import BrowserManager, BrowserSession
from src.workers.playwright.helpers.locators import get_field_locator
from src.workers.playwright.helpers.upload import upload_resume
from src.workers.playwright.strategy import PlaywrightPortalStrategy


@pytest.fixture
def mock_browser_manager():
    manager = AsyncMock(spec=BrowserManager)

    mock_session = MagicMock(spec=BrowserSession)

    # Page has sync methods for locators, async methods for actions
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.title = AsyncMock(return_value="Job Application")

    # Mock locator
    mock_locator = MagicMock()
    mock_locator.count = AsyncMock(return_value=1)
    mock_locator.fill = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.set_input_files = AsyncMock()

    mock_locator.or_ = MagicMock(return_value=mock_locator)
    mock_locator.first = mock_locator

    mock_page.get_by_label.return_value = mock_locator
    mock_page.get_by_placeholder.return_value = mock_locator
    mock_page.get_by_role.return_value = mock_locator
    mock_page.locator.return_value = mock_locator

    mock_session.page = mock_page
    manager.create_session.return_value = mock_session
    return manager


@pytest.fixture
def mock_context():
    job = MagicMock()
    job.url = "https://test-portal.com/job/1"
    job.portal_name = "test-portal"

    resume = MagicMock()
    resume.content = "/tmp/fake-resume.pdf"

    ctx = WorkerContext(application=MagicMock(), job=job, resume=resume)
    return ctx


@pytest.mark.asyncio
async def test_successful_execution(mock_browser_manager, mock_context):
    strategy = PlaywrightPortalStrategy(browser_manager=mock_browser_manager)
    mock_page = mock_browser_manager.create_session.return_value.page

    with (
        patch(
            "src.workers.playwright.strategy.capture_screenshot", new_callable=AsyncMock
        ) as mock_screenshot,
        patch(
            "src.workers.playwright.strategy.upload_resume", new_callable=AsyncMock
        ) as mock_upload,
    ):

        mock_screenshot.return_value = "/tmp/screenshot.png"

        result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.success
        assert result.metadata["screenshot_path"] == "/tmp/screenshot.png"
        assert "elapsed_ms" in result.metadata

        mock_browser_manager.create_session.assert_called_once_with(
            profile_id="test-portal"
        )
        mock_browser_manager.close_session.assert_called_once()
        mock_page.goto.assert_called_once_with(
            "https://test-portal.com/job/1", timeout=30000
        )
        mock_page.wait_for_load_state.assert_called_with("domcontentloaded")
        mock_upload.assert_called_once()


@pytest.mark.asyncio
async def test_retryable_navigation_timeout(mock_browser_manager, mock_context):
    strategy = PlaywrightPortalStrategy(browser_manager=mock_browser_manager)
    mock_page = mock_browser_manager.create_session.return_value.page
    mock_page.goto.side_effect = PlaywrightTimeoutError("Timeout")

    with patch(
        "src.workers.playwright.strategy.capture_screenshot", new_callable=AsyncMock
    ):
        result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert "navigation timeout" in result.error_message.lower()


@pytest.mark.asyncio
async def test_retryable_browser_crash(mock_browser_manager, mock_context):
    strategy = PlaywrightPortalStrategy(browser_manager=mock_browser_manager)
    mock_page = mock_browser_manager.create_session.return_value.page
    mock_page.goto.side_effect = PlaywrightError("Target closed")

    with patch(
        "src.workers.playwright.strategy.capture_screenshot", new_callable=AsyncMock
    ):
        result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert "browser crash or network failure" in result.error_message.lower()


@pytest.mark.asyncio
async def test_terminal_application_closed(mock_browser_manager, mock_context):
    strategy = PlaywrightPortalStrategy(browser_manager=mock_browser_manager)
    mock_page = mock_browser_manager.create_session.return_value.page
    mock_page.title.return_value = "404 Not Found"

    with patch(
        "src.workers.playwright.strategy.capture_screenshot", new_callable=AsyncMock
    ):
        result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "application closed" in result.error_message.lower()


@pytest.mark.asyncio
async def test_terminal_upload_failure(mock_browser_manager, mock_context):
    strategy = PlaywrightPortalStrategy(browser_manager=mock_browser_manager)

    with (
        patch(
            "src.workers.playwright.strategy.upload_resume", new_callable=AsyncMock
        ) as mock_upload,
        patch(
            "src.workers.playwright.strategy.capture_screenshot", new_callable=AsyncMock
        ),
    ):
        mock_upload.side_effect = Exception("Upload failed")

        result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "resume upload failed" in result.error_message.lower()


@pytest.mark.asyncio
async def test_terminal_missing_submit(mock_browser_manager, mock_context):
    strategy = PlaywrightPortalStrategy(browser_manager=mock_browser_manager)
    mock_page = mock_browser_manager.create_session.return_value.page

    # Missing submit button - we need to make count() return 0 when called for the button
    # get_by_role is used for submit button
    mock_submit_locator = MagicMock()
    mock_submit_locator.count = AsyncMock(return_value=0)
    mock_page.get_by_role.return_value = mock_submit_locator

    with (
        patch("src.workers.playwright.strategy.upload_resume", new_callable=AsyncMock),
        patch(
            "src.workers.playwright.strategy.capture_screenshot", new_callable=AsyncMock
        ),
    ):
        result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "required field missing" in result.error_message.lower()


@pytest.mark.asyncio
async def test_browser_manager_lifecycle():
    with patch("src.workers.playwright.browser.async_playwright") as mock_pw:
        mock_playwright_mgr = MagicMock()
        mock_playwright_instance = AsyncMock()
        mock_playwright_mgr.start = AsyncMock(return_value=mock_playwright_instance)
        mock_pw.return_value = mock_playwright_mgr

        mock_context = AsyncMock()
        mock_page = MagicMock()
        mock_context.pages = [mock_page]
        mock_playwright_instance.chromium.launch_persistent_context.return_value = (
            mock_context
        )

        manager = BrowserManager()
        session = await manager.create_session("test_profile")

        assert session.context == mock_context
        assert session.page == mock_page
        mock_playwright_instance.chromium.launch_persistent_context.assert_called_once()

        await manager.close_session(session)
        mock_context.close.assert_called_once()

        await manager.shutdown()
        mock_playwright_instance.stop.assert_called_once()


@pytest.mark.asyncio
async def test_locator_selection():
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.or_ = MagicMock(return_value=mock_locator)
    mock_page.get_by_label.return_value = mock_locator
    mock_page.get_by_placeholder.return_value = mock_locator
    mock_page.get_by_role.return_value = mock_locator

    locator = get_field_locator(mock_page, "First Name")
    assert locator is not None
    mock_page.get_by_label.assert_called_once_with("First Name", exact=False)


@pytest.mark.asyncio
async def test_upload_resume():
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_locator.first = mock_locator
    mock_locator.set_input_files = AsyncMock()
    mock_page.locator.return_value = mock_locator

    await upload_resume(mock_page, "/tmp/test.pdf")
    mock_page.locator.assert_called_once_with('input[type="file"]')
    mock_locator.set_input_files.assert_called_once_with("/tmp/test.pdf")


@pytest.mark.asyncio
async def test_browser_session_closed_on_exception(mock_browser_manager, mock_context):
    strategy = PlaywrightPortalStrategy(browser_manager=mock_browser_manager)
    mock_page = mock_browser_manager.create_session.return_value.page

    # Force an exception inside the try block (e.g., during navigation)
    mock_page.goto.side_effect = Exception("Unexpected error")

    with patch(
        "src.workers.playwright.strategy.capture_screenshot", new_callable=AsyncMock
    ):
        result = await strategy.execute(mock_context)

        # Verify the exception was caught and mapped to a failure
        assert result.outcome == WorkerOutcome.terminal_failure

        # Most importantly, verify close_session was called despite the exception
        mock_browser_manager.close_session.assert_called_once()
