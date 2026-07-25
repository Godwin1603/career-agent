from typing import Optional

from pydantic import BaseModel


class ParsedJob(BaseModel):
    """
    Intermediate DTO representing fields parsed deterministically
    from the raw Telegram message text.
    """

    company_name: Optional[str] = None
    role_title: Optional[str] = None
    location: Optional[str] = None
    is_remote: Optional[bool] = None
    application_url: Optional[str] = None
    email_address: Optional[str] = None
    google_form_url: Optional[str] = None
    salary_range: Optional[str] = None
    detected_portal: Optional[str] = None

    # Extra parsed fields requested by Phase 4 prompt, but not in Job DB model
    experience: Optional[str] = None
    employment_type: Optional[str] = None
    application_deadline: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[dict] = None


class AIEnrichmentResponse(BaseModel):
    """
    Structured output expected from the Gemini AI enrichment prompt.
    Must perfectly map to what the AI is expected to produce.
    """

    company_name: Optional[str] = None
    role_title: Optional[str] = None
    location: Optional[str] = None
    is_remote: Optional[bool] = None
    application_url: Optional[str] = None
    email_address: Optional[str] = None
    google_form_url: Optional[str] = None
    salary_range: Optional[str] = None
    detected_portal: Optional[str] = None

    # Enrichment fields
    relevance_score: float
    reasoning: str
    confidence: float
    prompt_version: Optional[str] = None
