"""
Prompt builder for job extraction and enrichment.
"""


class JobExtractionPromptBuilder:
    """
    Builds prompts for extracting structured data from raw job descriptions.
    """

    TEMPLATE = """
You are an expert AI recruiting assistant. Your task is to analyze the following raw job description
and extract structured information exactly matching the provided JSON schema.

Analyze the raw text and extract:
1. company_name: Name of the hiring company.
2. role_title: The job title.
3. location: The location of the job.
4. is_remote: Boolean indicating if the role is remote.
5. application_url: The primary URL to apply.
6. email_address: An email address for applying.
7. google_form_url: A Google Form URL if present.
8. salary_range: The salary range mentioned.
9. detected_portal: The name of the ATS or career portal (e.g. greenhouse, lever, workday) if inferable from URL.
10. relevance_score: A score from 0 to 100 indicating how relevant this job is for a senior backend engineer using Python/Go.
11. reasoning: A short sentence explaining why you assigned this relevance score.
12. confidence: A float from 0.0 to 1.0 indicating your confidence in this extraction.

Return ONLY valid JSON matching the schema. Do not include markdown formatting or extra text.

RAW JOB DESCRIPTION:
{raw_text}
"""

    PROMPT_VERSION = "v1"

    @classmethod
    def build_prompt(cls, raw_text: str) -> str:
        """
        Constructs the complete prompt string.
        """
        return cls.TEMPLATE.strip().format(raw_text=raw_text)

    @classmethod
    def get_version(cls) -> str:
        return cls.PROMPT_VERSION
