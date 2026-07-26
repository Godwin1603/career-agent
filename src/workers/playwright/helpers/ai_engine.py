"""
AI Answer Engine for Google Forms automation.
Generates concise professional responses using Gemini via Vertex AI REST API.
"""

import asyncio
import json
import logging
import urllib.request
from typing import Optional

from src.core.config import settings

logger = logging.getLogger(__name__)


class GoogleFormsAIAnswerEngine:
    """
    Lightweight Gemini wrapper using Vertex AI REST API to generate
    answers for descriptive form fields without introducing heavy AI libraries.
    """

    def __init__(
        self,
        project_id: str | None = None,
        location: str | None = None,
        model: str | None = None,
    ):
        self.project_id = project_id or settings.GCP_PROJECT_ID
        self.location = location or settings.VERTEX_AI_LOCATION
        self.model = model or settings.GEMINI_MODEL

    def _sync_generate_answer(self, prompt: str) -> str:
        """Synchronous REST call to Vertex AI."""
        try:
            import google.auth
            import google.auth.transport.requests

            credentials, project = google.auth.default()
            auth_req = google.auth.transport.requests.Request()
            credentials.refresh(auth_req)
            token = credentials.token
        except ImportError:
            # Fallback for local testing without google-auth
            token = "fake-token"

        url = (
            f"https://{self.location}-aiplatform.googleapis.com/v1/projects/"
            f"{self.project_id}/locations/{self.location}/publishers/google/"
            f"models/{self.model}:generateContent"
        )

        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 256,
            },
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15.0) as response:
                resp_data = json.loads(response.read().decode("utf-8"))

                # Extract text
                candidates = resp_data.get("candidates", [])
                if not candidates:
                    return ""

                content = candidates[0].get("content", {})
                parts = content.get("parts", [])
                if not parts:
                    return ""

                return parts[0].get("text", "").strip()
        except Exception as e:
            logger.warning("AI generation failed, returning empty string: %s", e)
            return ""

    async def generate_answer(
        self, question: str, candidate_context: Optional[str] = None
    ) -> str:
        """
        Generate a concise professional response to a form question.

        Args:
            question: The form question (e.g., "Why do you want to join us?")
            candidate_context: Optional context to personalize the answer.
        """
        system_instruction = (
            "You are a professional candidate filling out a job application. "
            "Generate a concise, professional answer to the following question. "
            "Keep it strictly under 50 words. Do not use markdown."
        )
        if candidate_context:
            system_instruction += (
                f"\nCandidate Background Context:\n{candidate_context}"
            )

        full_prompt = f"{system_instruction}\n\nQuestion: {question}\nAnswer:"

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_generate_answer, full_prompt)
