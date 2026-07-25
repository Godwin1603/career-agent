"""
Gemini AI Client Abstraction.
"""

from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AIError(Exception):
    """Base exception for AI operations."""

    pass


class AIRetryableError(AIError):
    """
    Exception raised when an AI operation fails but can be retried.
    Includes:
    - timeout
    - HTTP 5xx errors
    - rate limiting (429)
    - temporary Vertex AI failures
    """

    pass


class AIValidationError(AIError):
    """
    Exception raised when the AI returns output that cannot be processed.
    Non-retryable.
    Includes:
    - invalid schema
    - validation failure
    - unsupported response
    """

    pass


class GeminiClient:
    """
    Client for interacting with Google Gemini (Vertex AI).

    This client expects to output structured JSON matching a provided Pydantic schema.
    """

    def __init__(
        self,
        project_id: str = "test-project",
        location: str = "us-central1",
        model_name: str = "gemini-1.5-flash",
    ):
        self.project_id = project_id
        self.location = location
        self.model_name = model_name

    async def generate_structured(self, prompt: str, schema: Type[T]) -> T:
        """
        Send a prompt to Gemini and expect a response matching the Pydantic schema `schema`.

        Args:
            prompt: The text prompt.
            schema: A Pydantic BaseModel subclass defining the expected output.

        Returns:
            An instance of `schema`.

        Raises:
            AIRetryableError: On timeouts or 5xx HTTP errors.
            AIValidationError: On schema validation failure or malformed JSON.
        """
        # Note: Implementation is intentionally stubbed as requested by the prompt
        # "Do not call real Vertex AI".
        # A real implementation would use vertexai.generative_models or httpx here.
        raise NotImplementedError(
            "Real Vertex AI call is disabled by Phase 5 constraints."
        )
