"""
Data Transfer Objects for the Playwright Portal Strategy.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class PortalResult(BaseModel):
    """
    Result returned after portal execution.
    """

    success: bool
    failure_reason: Optional[str] = None
    submission_reference: Optional[str] = None
    screenshot_path: Optional[str] = None
    elapsed_ms: int = 0

    model_config = ConfigDict(frozen=True)


class PortalContext(BaseModel):
    """
    Data context passed down into the portal execution flow.
    Contains the extracted application data required to fill out forms.
    """

    job_url: str
    first_name: str = "Unknown"
    last_name: str = "Unknown"
    email: str = "unknown@example.com"
    phone: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    resume_path: Optional[str] = None
    cover_letter_path: Optional[str] = None

    model_config = ConfigDict(frozen=True)
