"""ToolRouter — maps detected intent + state to MCP tool calls."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp_tools.registry import ToolRegistry
from app.state_machine.states import State

logger = logging.getLogger(__name__)

# Mapping of (intent, state) → (tool_name, entity_to_kwarg_mapping)
# The entity_to_kwarg_mapping converts extracted entities to tool kwargs.
_INTENT_STATE_TOOL_MAP: dict[tuple[str, State], dict[str, Any]] = {
    # Agreement states: agree → record_agreement with accepted=True
    ("agree", State.PRIVACY_POLICY_PENDING): {
        "tool": "record_agreement",
        "kwargs": {"agreement_type": "privacy_policy", "accepted": True},
        "entity_map": {},
    },
    ("agree", State.HOUSE_RULES_PENDING): {
        "tool": "record_agreement",
        "kwargs": {"agreement_type": "house_rules", "accepted": True},
        "entity_map": {},
    },
    ("agree", State.RENTAL_AGREEMENT_PENDING): {
        "tool": "record_agreement",
        "kwargs": {"agreement_type": "rental_agreement", "accepted": True},
        "entity_map": {},
    },
    # Agreement states: decline → record_agreement with accepted=False
    ("decline", State.PRIVACY_POLICY_PENDING): {
        "tool": "record_agreement",
        "kwargs": {"agreement_type": "privacy_policy", "accepted": False},
        "entity_map": {},
    },
    ("decline", State.HOUSE_RULES_PENDING): {
        "tool": "record_agreement",
        "kwargs": {"agreement_type": "house_rules", "accepted": False},
        "entity_map": {},
    },
    ("decline", State.RENTAL_AGREEMENT_PENDING): {
        "tool": "record_agreement",
        "kwargs": {"agreement_type": "rental_agreement", "accepted": False},
        "entity_map": {},
    },
    # Info verify: confirm → trigger_otp (guest confirmed info is correct)
    # Note: "confirm" is now a self-transition — stays in INFO_VERIFY_PENDING
    # so the guest must then enter the OTP code to advance via "verify_otp"
    ("confirm", State.INFO_VERIFY_PENDING): {
        "tool": "trigger_otp",
        "kwargs": {},
        "entity_map": {},
    },
    # Info verify: verify_otp → verify OTP code, then advance to ID_VERIFY_PENDING
    ("verify_otp", State.INFO_VERIFY_PENDING): {
        "tool": "verify_otp",
        "kwargs": {},
        "entity_map": {"otp_code": "otp_code"},
    },
    # Info verify: provide_info → update_guest_info
    ("provide_info", State.INFO_VERIFY_PENDING): {
        "tool": "update_guest_info",
        "kwargs": {},
        "entity_map": {
            "first_name": "first_name",
            "last_name": "last_name",
            "phone": "phone",
        },
    },
    # ID verify: upload_id → record_id_upload (guest confirmed upload)
    # file_path is a placeholder — actual upload happens via /api/v1/id-upload endpoint
    ("upload_id", State.ID_VERIFY_PENDING): {
        "tool": "record_id_upload",
        "kwargs": {"file_path": "uploaded_via_secure_link"},
        "entity_map": {},
    },
    # ID verify: agree/upload → generate_id_upload_link
    ("agree", State.ID_VERIFY_PENDING): {
        "tool": "generate_id_upload_link",
        "kwargs": {},
        "entity_map": {},
    },
    # Incidental protection: select_option → record_incidental_selection
    ("select_option", State.INCIDENTAL_PROTECTION_PENDING): {
        "tool": "record_incidental_selection",
        "kwargs": {},
        "entity_map": {"selection_type": "selection_type"},
    },
    # Question → get_faq_answer (works in any state)
}

# States where "question" intent should call get_faq_answer
_QUESTION_STATES = {
    State.PRIVACY_POLICY_PENDING,
    State.HOUSE_RULES_PENDING,
    State.RENTAL_AGREEMENT_PENDING,
    State.INFO_VERIFY_PENDING,
    State.ID_VERIFY_PENDING,
    State.INCIDENTAL_PROTECTION_PENDING,
}

# States where "request_help" intent does not call a tool
_HELP_STATES = {
    State.PRIVACY_POLICY_PENDING,
    State.HOUSE_RULES_PENDING,
    State.RENTAL_AGREEMENT_PENDING,
    State.INFO_VERIFY_PENDING,
    State.ID_VERIFY_PENDING,
    State.INCIDENTAL_PROTECTION_PENDING,
    State.REFUSED,
    State.COMPLETED,
}


class ToolRouter:
    """Routes detected intent + state to the appropriate MCP tool call.

    Usage::

        router = ToolRouter(tool_registry)
        result = await router.route(
            intent="agree",
            entities={},
            state=State.PRIVACY_POLICY_PENDING,
            session_id="abc-123",
            db_session=db,
        )
    """

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self._registry = tool_registry

    async def route(
        self,
        intent: str,
        entities: dict,
        state: State,
        session_id: str,
        db_session: AsyncSession,
    ) -> dict[str, Any]:
        """Map intent + state to an MCP tool call and execute it.

        Args:
            intent: The detected intent (e.g., "agree", "decline").
            entities: Extracted entities from the guest's message.
            state: The current state machine state.
            session_id: The current check-in session ID.
            db_session: Async database session.

        Returns:
            Tool result dict, or a dict with "no_tool" key if no tool
            should be called.
        """
        # Handle "question" intent — call get_faq_answer
        if intent == "question" and state in _QUESTION_STATES:
            return await self._call_tool(
                "get_faq_answer",
                db_session=db_session,
                session_id=session_id,
                question=entities.get("question", ""),
            )

        # Handle "request_help" — no tool call, just return info
        if intent == "request_help" and state in _HELP_STATES:
            return {
                "no_tool": True,
                "intent": "request_help",
                "message": (
                    "A human agent will be notified to assist you. "
                    "Please hold on."
                ),
            }

        # Handle "greeting" in INIT state — no tool call
        if intent == "greeting" and state == State.INIT:
            return {
                "no_tool": True,
                "intent": "greeting",
                "message": "Welcome! Let's begin your check-in.",
            }

        # Handle "other" — no tool call
        if intent == "other":
            return {
                "no_tool": True,
                "intent": "other",
                "message": "I didn't understand that. Could you rephrase?",
            }

        # Look up the tool mapping
        key = (intent, state)
        mapping = _INTENT_STATE_TOOL_MAP.get(key)

        if mapping is None:
            # Some intents are pure state transitions (start, confirm,
            # upload_id, resume) that don't need tool calls.
            logger.debug(
                "No tool mapping for intent=%s state=%s", intent, state.value
            )
            return {
                "no_tool": True,
                "intent": intent,
                "message": "I'm not sure how to handle that right now.",
            }

        tool_name = mapping["tool"]
        kwargs = dict(mapping["kwargs"])  # copy static kwargs
        entity_map = mapping.get("entity_map", {})

        # Special case: verify_otp at INFO_VERIFY_PENDING — only advance if OTP verified
        if key == ("verify_otp", State.INFO_VERIFY_PENDING):
            # The verify_otp tool will return {"verified": True/False}
            # We need the session_manager to check this before advancing
            pass

        # Map entities to tool kwargs
        for entity_key, kwarg_name in entity_map.items():
            if entity_key in entities and entities[entity_key] is not None:
                kwargs[kwarg_name] = entities[entity_key]

        # Add session_id to kwargs
        kwargs["session_id"] = session_id

        return await self._call_tool(tool_name, db_session=db_session, **kwargs)

    async def _call_tool(
        self, tool_name: str, db_session: AsyncSession, **kwargs: Any
    ) -> dict[str, Any]:
        """Call a registered MCP tool by name."""
        handler = self._registry.get_tool(tool_name)
        if handler is None:
            logger.error("Tool not found: %s", tool_name)
            return {"error": f"Tool '{tool_name}' not found"}

        try:
            result = await handler(db_session=db_session, **kwargs)
            if result is None:
                return {"result": "ok"}
            return result
        except Exception as exc:
            logger.error(
                "Tool '%s' execution failed: %s", tool_name, exc
            )
            return {"error": f"Tool execution failed: {exc}"}
