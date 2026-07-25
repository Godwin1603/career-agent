"""
Resilient locators for portal forms.
"""

from playwright.async_api import Locator, Page


def get_field_locator(page: Page, label_text: str) -> Locator:
    """
    Attempts to find a resilient locator for a given field name.
    Prefer: label, placeholder, role, name.
    Avoid brittle XPath where possible.
    """
    return (
        page.get_by_label(label_text, exact=False)
        .or_(page.get_by_placeholder(label_text, exact=False))
        .or_(page.get_by_role("textbox", name=label_text, exact=False))
        .first
    )
