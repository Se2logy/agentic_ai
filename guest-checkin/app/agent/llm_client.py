"""OllamaClient — async HTTP client for the Ollama LLM API."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.agent.exceptions import OllamaUnavailableError

logger = logging.getLogger(__name__)


class OllamaClient:
    """Async client for the Ollama /api/chat endpoint.

    Usage::

        client = OllamaClient(base_url="http://localhost:11434", model="llama3.1:8b")
        response = await client.chat(messages=[{"role": "user", "content": "Hello"}])
        print(response["message"]["content"])
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.1:8b",
        timeout: int = 30,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request to Ollama.

        Args:
            messages: List of message dicts with "role" and "content".
            tools: Optional list of tool definitions for function calling.

        Returns:
            Parsed response dict with "message" key containing the
            assistant's reply.

        Raises:
            OllamaUnavailableError: If Ollama is unreachable after retries.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 2):  # +2 = initial + retries
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                ) as client:
                    resp = await client.post(
                        f"{self.base_url}/api/chat",
                        json=payload,
                    )
                    resp.raise_for_status()
                    return resp.json()

            except httpx.ConnectError as exc:
                last_error = exc
                logger.warning(
                    "Ollama connect error (attempt %d/%d): %s",
                    attempt,
                    self.max_retries + 1,
                    exc,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "Ollama timeout (attempt %d/%d): %s",
                    attempt,
                    self.max_retries + 1,
                    exc,
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                logger.warning(
                    "Ollama HTTP %s (attempt %d/%d): %s",
                    exc.response.status_code,
                    attempt,
                    self.max_retries + 1,
                    exc,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "Ollama HTTP error (attempt %d/%d): %s",
                    attempt,
                    self.max_retries + 1,
                    exc,
                )

        raise OllamaUnavailableError(self.base_url, self.max_retries)
