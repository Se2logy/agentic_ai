"""Custom exceptions for the LLM agent module."""


class OllamaUnavailableError(Exception):
    """Raised when the Ollama LLM service is unreachable after retries."""

    def __init__(self, base_url: str, retries: int) -> None:
        self.base_url = base_url
        self.retries = retries
        super().__init__(
            f"Ollama unavailable at {base_url} after {retries} retries"
        )


class IntentDetectionError(Exception):
    """Raised when intent detection fails via both LLM and fallback."""

    def __init__(self, message: str = "Intent detection failed") -> None:
        super().__init__(message)


class EntityExtractionError(Exception):
    """Raised when entity extraction fails via both LLM and fallback."""

    def __init__(self, message: str = "Entity extraction failed") -> None:
        super().__init__(message)
