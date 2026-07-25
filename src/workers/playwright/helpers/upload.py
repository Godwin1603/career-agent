"""
Resume upload helpers.
"""

from typing import Union

from playwright.async_api import Locator, Page


async def upload_resume(
    page: Page, file_path: str, locator: Union[Locator, str] = 'input[type="file"]'
) -> None:
    """
    Upload a resume file.
    Supports <input type=file> and hidden file inputs using set_input_files.
    """
    if isinstance(locator, str):
        file_input = page.locator(locator).first
    else:
        file_input = locator.first

    # set_input_files works on hidden inputs as long as they are type=file
    await file_input.set_input_files(file_path)
