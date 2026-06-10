"""LLM agent module — client, intent detection, entity extraction, tool routing, fallback."""

from app.agent.exceptions import (
    EntityExtractionError,
    IntentDetectionError,
    OllamaUnavailableError,
)
from app.agent.entity_extractor import EntityExtractor
from app.agent.fallback import FallbackAgent
from app.agent.intent import IntentDetector
from app.agent.llm_client import OllamaClient
from app.agent.prompt_builder import PromptBuilder
from app.agent.tool_router import ToolRouter

__all__ = [
    "EntityExtractor",
    "EntityExtractionError",
    "FallbackAgent",
    "IntentDetector",
    "IntentDetectionError",
    "OllamaClient",
    "OllamaUnavailableError",
    "PromptBuilder",
    "ToolRouter",
]
