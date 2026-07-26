"""
Google Forms specific DOM interaction helpers using Playwright.
"""

import logging

from playwright.async_api import Locator, Page

logger = logging.getLogger(__name__)


async def get_question_blocks(page: Page) -> list[Locator]:
    """Retrieve all question blocks (usually role=listitem) on the current page."""
    # Google Forms wraps questions in listitems.
    return await page.get_by_role("listitem").all()


async def get_question_title(block: Locator) -> str:
    """Extract the question title/text from a block."""
    # Usually the question title has role="heading" or is just the first text block
    heading = block.get_by_role("heading")
    if await heading.count() > 0:
        return await heading.first.inner_text()

    # Fallback to the first div's text
    return await block.locator("div").first.inner_text()


async def fill_field(block: Locator, value: str) -> None:
    """
    Attempt to fill a value into a supported widget within the block.
    Supports: Short Answer, Paragraph, Multiple Choice (Radio), Checkboxes.
    Skips if unsupported.
    """
    if not value:
        return

    # 1. Text Inputs (Short Answer)
    text_input = block.locator('input[type="text"], input:not([type])')
    if await text_input.count() > 0:
        await text_input.first.fill(value)
        return

    # 2. Textarea (Paragraph)
    textarea = block.locator("textarea")
    if await textarea.count() > 0:
        await textarea.first.fill(value)
        return

    # 3. Radio Buttons (Multiple Choice / Linear Scale)
    radios = block.get_by_role("radio")
    if await radios.count() > 0:
        # Try to find a radio matching the value
        target = radios.filter(has_text=value)
        if await target.count() > 0:
            await target.first.click()
        else:
            # Fallback to first if value not exactly matching
            await radios.first.click()
        return

    # 4. Checkboxes
    checkboxes = block.get_by_role("checkbox")
    if await checkboxes.count() > 0:
        target = checkboxes.filter(has_text=value)
        if await target.count() > 0:
            # Ensure it's checked
            is_checked = await target.first.get_attribute("aria-checked")
            if is_checked != "true":
                await target.first.click()
        else:
            await checkboxes.first.click()
        return

    # 5. Dropdown (Listbox)
    listbox = block.get_by_role("listbox")
    if await listbox.count() > 0:
        await listbox.first.click()
        # Wait for options to appear and select
        page = block.page
        option = page.get_by_role("option", name=value)
        if await option.count() > 0:
            await option.first.click()
        else:
            # fallback: just click the first available option
            options = page.get_by_role("option")
            if await options.count() > 0:
                await options.first.click()
        return

    logger.debug("Unsupported or unrecognized widget in block.")


async def handle_file_upload(page: Page, block: Locator, file_path: str) -> None:
    """
    Handle Google Forms file upload widget.
    Usually it opens an iframe or uses a specific input. We will use the generic
    upload_resume helper for the input[type="file"] if it's available.
    """
    file_input = block.locator('input[type="file"]')
    if await file_input.count() > 0:
        await file_input.first.set_input_files(file_path)
    else:
        # If it's a "Add file" button that pops a dialog, this requires a more
        # complex interception which is abstracted by upload_resume helper
        add_button = block.get_by_role("button").filter(has_text="Add file")
        if await add_button.count() > 0:
            async with page.expect_file_chooser() as fc_info:
                await add_button.first.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(file_path)
