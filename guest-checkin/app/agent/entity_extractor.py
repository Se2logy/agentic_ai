"""EntityExtractor — extracts structured entities from guest messages."""

from __future__ import annotations

import json
import logging
import re

from app.agent.exceptions import EntityExtractionError, OllamaUnavailableError
from app.agent.llm_client import OllamaClient
from app.state_machine.states import State

logger = logging.getLogger(__name__)

# Regex patterns for fallback entity extraction
_PHONE_PATTERN = re.compile(
    r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}",
)
_NAME_PATTERN = re.compile(
    r"(?:my name is|i'm|i am|this is|call me)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
    re.IGNORECASE,
)
_FIRST_LAST_PATTERN = re.compile(
    r"([A-Z][a-z]+)\s+([A-Z][a-z]+)",
)
_OTP_PATTERN = re.compile(r"\b(\d{6})\b")

# LLM extraction prompts by state
_EXTRACT_PROMPTS: dict[State, str] = {
    State.INFO_VERIFY_PENDING: """Extract the following entities from the guest's message:
- first_name: Guest's first name (if provided)
- last_name: Guest's last name (if provided)
- phone: Guest's phone number (if provided)
- otp_code: 6-digit OTP code (if provided)

Guest message: "{message}"

Respond with ONLY a JSON object, no other text. Example:
{{"first_name": "John", "last_name": "Doe", "phone": "+1234567890", "otp_code": null}}

If an entity is not found in the message, use null for its value.""",
    State.INCIDENTAL_PROTECTION_PENDING: """Extract the following entity from the guest's message:
- selection_type: Either "damage_waiver" or "security_hold" based on what the guest chose

Guest message: "{message}"

Respond with ONLY a JSON object, no other text. Example:
{{"selection_type": "damage_waiver"}}

If the selection is unclear, use null for the value.""",
}


class EntityExtractor:
    """Extract structured entities from guest messages.

    Uses Ollama with structured extraction prompts, with regex fallback.
    """

    def __init__(self, llm_client: OllamaClient) -> None:
        self._llm = llm_client

    async def extract_entities(
        self, message: str, state: State
    ) -> dict:
        """Extract entities from a guest message based on the current state.

        Args:
            message: The guest's message text.
            state: The current state machine state.

        Returns:
            Dict of extracted entities (keys depend on state).

        Raises:
            EntityExtractionError: If extraction fails entirely.
        """
        # Only extract for states that have entity extraction needs
        if state not in _EXTRACT_PROMPTS:
            return {}

        # Try LLM first
        try:
            entities = await self._extract_llm(message, state)
            if entities:
                logger.debug(
                    "LLM entities extracted: %s (state=%s)",
                    entities,
                    state.value,
                )
                return entities
        except OllamaUnavailableError:
            logger.info("Ollama unavailable, using regex fallback for entities")
        except Exception as exc:
            logger.warning("LLM entity extraction failed: %s", exc)

        # Fallback to regex
        try:
            entities = self._extract_regex(message, state)
            logger.debug(
                "Regex entities extracted: %s (state=%s)",
                entities,
                state.value,
            )
            return entities
        except Exception as exc:
            raise EntityExtractionError(
                f"Entity extraction failed: {exc}"
            ) from exc

    async def _extract_llm(self, message: str, state: State) -> dict:
        """Use Ollama to extract entities."""
        prompt_template = _EXTRACT_PROMPTS.get(state)
        if not prompt_template:
            return {}

        prompt = prompt_template.format(message=message)

        response = await self._llm.chat(
            messages=[{"role": "user", "content": prompt}]
        )

        content = response.get("message", {}).get("content", "").strip()

        # Try to parse JSON from the response
        # The LLM may wrap the JSON in markdown code blocks
        json_match = re.search(r"\{[^}]+\}", content, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                logger.warning("Failed to parse LLM JSON: %s", content)

        return {}

    def _extract_regex(self, message: str, state: State) -> dict:
        """Extract entities using regex patterns (fallback)."""
        entities: dict = {}

        if state == State.INFO_VERIFY_PENDING:
            # Phone number
            phone_match = _PHONE_PATTERN.search(message)
            if phone_match:
                entities["phone"] = phone_match.group()

            # Name
            name_match = _NAME_PATTERN.search(message)
            if name_match:
                full_name = name_match.group(1).strip()
                parts = full_name.split(None, 1)
                entities["first_name"] = parts[0]
                if len(parts) > 1:
                    entities["last_name"] = parts[1]
            else:
                # Try simple first+last pattern
                fl_match = _FIRST_LAST_PATTERN.search(message)
                if fl_match:
                    entities["first_name"] = fl_match.group(1)
                    entities["last_name"] = fl_match.group(2)

            # OTP code
            otp_match = _OTP_PATTERN.search(message)
            if otp_match:
                entities["otp_code"] = otp_match.group(1)

        elif state == State.INCIDENTAL_PROTECTION_PENDING:
            lower = message.lower()
            if "damage" in lower and "waiver" in lower:
                entities["selection_type"] = "damage_waiver"
            elif "security" in lower and "hold" in lower:
                entities["selection_type"] = "security_hold"
            elif "option 1" in lower or "first" in lower:
                entities["selection_type"] = "damage_waiver"
            elif "option 2" in lower or "second" in lower:
                entities["selection_type"] = "security_hold"

        return entities
