"""
Unit tests for Google Forms automation strategy and helpers.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src.workers.dto import WorkerContext, WorkerOutcome
from src.workers.playwright.google_forms_strategy import GoogleFormsStrategy
from src.workers.playwright.helpers.ai_engine import GoogleFormsAIAnswerEngine
from src.workers.playwright.helpers.form_classifier import FieldType, classify_field


@pytest.fixture
def mock_browser_manager():
    manager = MagicMock()
    session = MagicMock()
    page = AsyncMock()
    session.page = page
    manager.create_session = AsyncMock(return_value=session)
    manager.close_session = AsyncMock()
    return manager


@pytest.fixture
def mock_ai_engine():
    engine = GoogleFormsAIAnswerEngine()
    engine.generate_answer = AsyncMock(return_value="AI Generated Answer")
    return engine


@pytest.fixture
def mock_context():
    context = MagicMock(spec=WorkerContext)
    context.job = MagicMock()
    context.job.url = "https://example.com/form"
    context.job.id = "job_123"
    context.resume = MagicMock()
    context.resume.content = "/path/to/resume.pdf"
    return context


class TestFormClassifier:
    def test_classify_profile(self):
        assert classify_field("What is your Name?") == FieldType.PROFILE
        assert classify_field("Email Address") == FieldType.PROFILE
        assert classify_field("Years of Experience") == FieldType.PROFILE

    def test_classify_ai(self):
        assert classify_field("Why do you want to join us?") == FieldType.AI
        assert classify_field("Describe your biggest challenge") == FieldType.AI

    def test_classify_upload(self):
        assert classify_field("Upload Resume") == FieldType.UPLOAD
        assert classify_field("Cover Letter") == FieldType.UPLOAD

    def test_classify_manual(self):
        assert classify_field("Please record a video") == FieldType.MANUAL
        assert classify_field("Complete the CAPTCHA") == FieldType.MANUAL

    def test_classify_unknown(self):
        assert classify_field("What is 2+2?") == FieldType.UNKNOWN
        assert classify_field("") == FieldType.UNKNOWN


class TestGoogleFormsStrategy:

    @patch("src.workers.playwright.google_forms_strategy.get_question_blocks")
    @patch("src.workers.playwright.google_forms_strategy.get_question_title")
    @patch("src.workers.playwright.google_forms_strategy.fill_field")
    @patch("src.workers.playwright.google_forms_strategy.handle_file_upload")
    @patch("src.workers.playwright.google_forms_strategy.capture_screenshot")
    @pytest.mark.asyncio
    async def test_success_submit_flow(
        self,
        mock_screenshot,
        mock_upload,
        mock_fill,
        mock_title,
        mock_blocks,
        mock_browser_manager,
        mock_ai_engine,
        mock_context,
    ):
        strategy = GoogleFormsStrategy(mock_browser_manager, mock_ai_engine)

        # Mock blocks (1 profile, 1 AI, 1 submit button)
        block1 = MagicMock()
        block2 = MagicMock()
        mock_blocks.return_value = [block1, block2]

        # Define titles sequentially
        mock_title.side_effect = ["Email Address", "Describe yourself"]

        page = mock_browser_manager.create_session.return_value.page
        page.title = AsyncMock(return_value="Application Form")

        # Mock submit button presence
        submit_btn = AsyncMock()
        submit_btn.count = AsyncMock(return_value=1)
        next_btn = AsyncMock()
        next_btn.count = AsyncMock(return_value=0)

        def get_by_role(role, name=None, exact=False):
            if role == "button" and name == "Submit":
                return submit_btn
            if role == "button" and name == "Next":
                return next_btn
            return AsyncMock()

        page.get_by_role = MagicMock(side_effect=get_by_role)
    
        mock_screenshot.return_value = "/path/to/shot.png"

        result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.success, result.error_message
        assert result.metadata["submission_reference"] == "google_forms_submitted"
        assert mock_fill.call_count == 2
        mock_ai_engine.generate_answer.assert_called_once()
        submit_btn.first.click.assert_called_once()

    @patch("src.workers.playwright.google_forms_strategy.get_question_blocks")
    @patch("src.workers.playwright.google_forms_strategy.get_question_title")
    @patch("src.workers.playwright.google_forms_strategy.capture_screenshot")
    @pytest.mark.asyncio
    async def test_manual_pause(
        self,
        mock_screenshot,
        mock_title,
        mock_blocks,
        mock_browser_manager,
        mock_ai_engine,
        mock_context,
    ):
        strategy = GoogleFormsStrategy(mock_browser_manager, mock_ai_engine)

        block = MagicMock()
        mock_blocks.return_value = [block]
        mock_title.return_value = "Upload an introductory video"

        page = mock_browser_manager.create_session.return_value.page
        page.title = AsyncMock(return_value="Application Form")

        result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert result.metadata["status"] == "WAITING_FOR_USER"
        assert "VIDEO" in result.metadata["reason"]

    @pytest.mark.asyncio
    async def test_deleted_form_is_terminal(
        self, mock_browser_manager, mock_ai_engine, mock_context
    ):
        strategy = GoogleFormsStrategy(mock_browser_manager, mock_ai_engine)
        page = mock_browser_manager.create_session.return_value.page
        page.title = AsyncMock(return_value="Form deleted")

        with patch(
            "src.workers.playwright.google_forms_strategy.capture_screenshot",
            return_value="shot.png",
        ):
            result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.terminal_failure
        assert "deleted" in result.error_message

    @pytest.mark.asyncio
    async def test_network_timeout_is_retryable(
        self, mock_browser_manager, mock_ai_engine, mock_context
    ):
        strategy = GoogleFormsStrategy(mock_browser_manager, mock_ai_engine)
        page = mock_browser_manager.create_session.return_value.page
        page.goto = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))

        with patch(
            "src.workers.playwright.google_forms_strategy.capture_screenshot",
            return_value="shot.png",
        ):
            result = await strategy.execute(mock_context)

        assert result.outcome == WorkerOutcome.retryable_failure
        assert "timeout" in result.error_message
