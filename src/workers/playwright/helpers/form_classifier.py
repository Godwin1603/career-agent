"""
Google Forms field classification.
"""

from enum import Enum


class FieldType(str, Enum):
    """Classification categories for Google Form fields."""

    PROFILE = "PROFILE"
    RULE = "RULE"
    AI = "AI"
    UPLOAD = "UPLOAD"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"


def classify_field(title: str) -> FieldType:
    """
    Classify a form field title into a FieldType.

    Args:
        title: The field title/question string.

    Returns:
        The mapped FieldType.
    """
    if not title:
        return FieldType.UNKNOWN

    t = title.lower()

    # Manual pause triggers
    if any(k in t for k in ("video", "camera", "microphone", "captcha")):
        return FieldType.MANUAL

    # Upload fields
    if any(k in t for k in ("resume", "cv", "cover letter", "portfolio", "upload")):
        return FieldType.UPLOAD

    # Profile fields (Deterministic mapping)
    profile_keywords = [
        "name",
        "email",
        "phone",
        "location",
        "linkedin",
        "github",
        "website",
        "current company",
        "college",
        "degree",
        "cgpa",
        "years of experience",
        "skills",
        "notice period",
        "salary",
        "work authorization",
        "visa",
        "sponsorship",
    ]
    if any(k in t for k in profile_keywords):
        return FieldType.PROFILE

    # Descriptive AI fields
    ai_keywords = [
        "why do you want to join",
        "describe",
        "challenge",
        "achievements",
        "leadership",
        "career goals",
        "strengths",
        "weaknesses",
        "tell us about",
        "experience with",
    ]
    if any(k in t for k in ai_keywords):
        return FieldType.AI

    return FieldType.UNKNOWN
