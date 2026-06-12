"""IntentDetector — detects guest intent from messages via LLM or regex fallback."""

from __future__ import annotations

import json
import logging
import re

from app.agent.exceptions import IntentDetectionError, OllamaUnavailableError
from app.agent.fallback import FallbackAgent
from app.agent.llm_client import OllamaClient
from app.state_machine.states import State

logger = logging.getLogger(__name__)

# Valid intents that the detector can return
VALID_INTENTS = frozenset({
    "agree",
    "decline",
    "confirm",
    "verify_otp",
    "upload_id",
    "question",
    "provide_info",
    "select_option",
    "request_help",
    "greeting",
    "other",
})

# Prompt for LLM-based intent classification
_INTENT_CLASSIFICATION_PROMPT = """You are an intent classifier for a hotel guest check-in assistant.

Current state: {state}
Required action: {required_action}

Classify the following guest message into exactly one of these intents:
- agree: Guest accepts, agrees, accepted, agreed, acknowledges, acknowledged, or confirms the current agreement
- decline: Guest declines, declined, refuses, refused, rejects, rejected, disagrees, disagreed, or says no to the current agreement
- confirm: Guest confirms their personal information is correct (used in INFO_VERIFY_PENDING)
- verify_otp: Guest is providing a 6-digit OTP verification code (a numeric code like "123456")
- upload_id: Guest confirms they have uploaded their ID document
- question: Guest is asking a question
- provide_info: Guest is providing or correcting personal information
- select_option: Guest is selecting an option (e.g., damage waiver vs security hold)
- request_help: Guest is asking for human assistance
- greeting: Guest is greeting the assistant
- other: None of the above

IMPORTANT: Recognize all word forms (e.g., "accepted", "agreed", "acknowledged" = agree; "declined", "refused", "rejected", "disagreed" = decline).
IMPORTANT: If the guest message contains a 6-digit number (like "123456" or "456789"), classify it as "verify_otp", NOT "agree" or "confirm".

Guest message: "{message}"

Respond with ONLY the intent label, nothing else. Example: agree"""


class IntentDetector:
    """Detect guest intent from a message.

    Primary: use Ollama LLM with a structured classification prompt.
    Fallback: regex patterns via FallbackAgent when LLM is unavailable.
    """

    def __init__(self, llm_client: OllamaClient) -> None:
        self._llm = llm_client
        self._fallback = FallbackAgent()

    async def detect_intent(self, message: str, state: State) -> str:
        """Detect intent from a guest message.

        Tries LLM first, falls back to regex if LLM fails.

        Args:
            message: The guest's message text.
            state: The current state machine state.

        Returns:
            One of the valid intent strings.

        Raises:
            IntentDetectionError: If both LLM and fallback fail.
        """
        # Try LLM-based detection first
        try:
            intent = await self._detect_intent_llm(message, state)
            if intent in VALID_INTENTS:
                logger.debug(
                    "LLM intent detected: %s (state=%s)", intent, state.value
                )
                return intent
            logger.warning(
                "LLM returned invalid intent '%s', falling back to regex",
                intent,
            )
        except OllamaUnavailableError:
            logger.info("Ollama unavailable, using regex fallback for intent")
        except Exception as exc:
            logger.warning("LLM intent detection failed: %s", exc)

        # Fallback to regex
        try:
            intent = self._fallback.detect_intent_regex(message, state)
            logger.debug(
                "Regex intent detected: %s (state=%s)", intent, state.value
            )
            return intent
        except Exception as exc:
            raise IntentDetectionError(
                f"Intent detection failed: {exc}"
            ) from exc

    async def _detect_intent_llm(self, message: str, state: State) -> str:
        """Use Ollama to classify the guest's intent."""
        from app.state_machine.states import STATE_INFO

        required_action = STATE_INFO.get(state, {}).get(
            "required_action", "Unknown"
        )
        prompt = _INTENT_CLASSIFICATION_PROMPT.format(
            state=state.value,
            required_action=required_action,
            message=message,
        )

        response = await self._llm.chat(
            messages=[{"role": "user", "content": prompt}]
        )

        # Parse the LLM response — it should be a single intent label
        content = response.get("message", {}).get("content", "").strip().lower()
        # Take only the first word/line in case the LLM adds extra text
        content = content.split("\n")[0].strip()
        content = re.sub(r"[^a-z_]", "", content)

        return content
