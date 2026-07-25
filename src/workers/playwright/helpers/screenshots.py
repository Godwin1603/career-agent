"""
Screenshot helper.
"""

import tempfile
import uuid
from pathlib import Path
from typing import Optional

from playwright.async_api import Page


async def capture_screenshot(page: Page, prefix: str = "screenshot") -> Optional[str]:
    """
    Captures a screenshot to a temporary path.
    """
    tmp_dir = Path(tempfile.gettempdir()) / "career_agent_screenshots"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    file_path = tmp_dir / f"{prefix}_{uuid.uuid4().hex[:8]}.png"

    try:
        await page.screenshot(path=str(file_path), full_page=True)
        return str(file_path)
    except Exception:
        return None
