import re

from src.jobs.dto import ParsedJob


class JobParser:
    """
    Deterministic parser for raw job postings. No AI.
    Relies on standard text matching and regex.
    """

    URL_REGEX = re.compile(r"https?://[^\s]+")
    EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    SALARY_REGEX = re.compile(r"\$\d+[kK]?\s*-\s*\$\d+[kK]?")

    @classmethod
    def parse(cls, text: str) -> ParsedJob:
        dto = ParsedJob()
        if not text:
            return dto

        dto.description = text
        cls._extract_urls(text, dto)
        cls._extract_email(text, dto)
        cls._extract_salary(text, dto)
        cls._extract_location_remote(text, dto)
        cls._extract_header(text, dto)
        return dto

    @classmethod
    def _extract_urls(cls, text: str, dto: ParsedJob) -> None:
        urls = cls.URL_REGEX.findall(text)
        for url in urls:
            if "docs.google.com/forms" in url or "forms.gle" in url:
                if not dto.google_form_url:
                    dto.google_form_url = url
            else:
                if not dto.application_url:
                    dto.application_url = url

    @classmethod
    def _extract_email(cls, text: str, dto: ParsedJob) -> None:
        emails = cls.EMAIL_REGEX.findall(text)
        if emails:
            dto.email_address = emails[0]

    @classmethod
    def _extract_salary(cls, text: str, dto: ParsedJob) -> None:
        salaries = cls.SALARY_REGEX.findall(text)
        if salaries:
            dto.salary_range = salaries[0]

    @classmethod
    def _extract_location_remote(cls, text: str, dto: ParsedJob) -> None:
        text_lower = text.lower()
        if (
            "remote" in text_lower
            or "wfh" in text_lower
            or "work from home" in text_lower
        ):
            dto.is_remote = True
        elif "hybrid" in text_lower:
            dto.is_remote = False

    @classmethod
    def _extract_header(cls, text: str, dto: ParsedJob) -> None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return

        first_line = lines[0]
        if " - " in first_line:
            parts = first_line.split(" - ", 1)
            dto.role_title = parts[0].strip()
            dto.company_name = parts[1].strip()
        elif " | " in first_line:
            parts = first_line.split(" | ", 1)
            dto.role_title = parts[0].strip()
            dto.company_name = parts[1].strip()
        else:
            dto.role_title = first_line
            if len(lines) > 1:
                dto.company_name = lines[1]
