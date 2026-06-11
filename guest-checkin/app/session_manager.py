"""SessionManager — orchestrates the full guest message flow.

Load session → detect intent → extract entities → route to MCP tool
→ advance state machine → generate response → save messages → return.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.entity_extractor import EntityExtractor
from app.agent.exceptions import OllamaUnavailableError
from app.agent.fallback import FallbackAgent
from app.agent.intent import IntentDetector
from app.agent.llm_client import OllamaClient
from app.agent.tool_router import ToolRouter
from app.config import settings
from app.mcp_tools.registry import tool_registry
from app.models.guest import Guest
from app.models.message import Message
from app.models.reservation import Reservation
from app.models.session import Session
from app.state_machine import InvalidTransitionError, StateMachine
from app.state_machine.states import STATE_INFO, State
from app.state_machine.transitions import can_transition, get_required_action
from app.utils import agreement_type_for_state, answer_question

logger = logging.getLogger(__name__)

# ── Module-level helpers ────────────────────────────────────────────


async def _fetch_reservation(
    session: Session, db: AsyncSession
) -> Reservation | None:
    """Fetch the reservation for a session's guest."""
    result = await db.execute(
        select(Reservation).where(Reservation.id == session.reservation_id)
    )
    return result.scalar_one_or_none()


async def _fetch_guest(
    session: Session, db: AsyncSession
) -> Guest | None:
    """Fetch the guest for a session."""
    result = await db.execute(
        select(Guest).where(Guest.id == session.guest_id)
    )
    return result.scalar_one_or_none()


async def _get_agreement_text(
    session: Session, agreement_type: str, db: AsyncSession
) -> str:
    """Fetch the actual agreement text from the reservation."""
    reservation = await _fetch_reservation(session, db)
    if reservation is None:
        return f"[{agreement_type.replace('_', ' ').title()} text — reservation data unavailable]"

    mapping = {
        "privacy_policy": reservation.privacy_policy_text,
        "house_rules": reservation.house_rules_text,
        "rental_agreement": reservation.rental_agreement_text,
    }
    text = mapping.get(agreement_type)
    if text:
        return text
    return f"[{agreement_type.replace('_', ' ').title()} text not found]"


# ── State-aware response templates ─────────────────────────────────

_STATE_RESPONSES: dict[State, str] = {
    State.PRIVACY_POLICY_PENDING: (
        "Please review our Privacy Policy and Data Usage agreement below. "
        "Reply 'agree' to accept or 'decline' to refuse."
    ),
    State.HOUSE_RULES_PENDING: (
        "Please review the House Rules below. "
        "Reply 'agree' to accept or 'decline' to refuse."
    ),
    State.RENTAL_AGREEMENT_PENDING: (
        "Please review the Rental Agreement below. "
        "Reply 'agree' to accept or 'decline' to refuse."
    ),
    State.INFO_VERIFY_PENDING: (
        "Please verify your information below. "
        "If everything is correct, reply 'confirm'. "
        "If anything needs updating, tell me what to change."
    ),
    State.ID_VERIFY_PENDING: (
        "Please upload your government-issued ID using the secure link provided."
    ),
    State.INCIDENTAL_PROTECTION_PENDING: (
        "Please select your incidental protection option using the link provided."
    ),
    State.COMPLETED: (
        "Your check-in is complete! Here are your arrival instructions."
    ),
    State.REFUSED: (
        "Your check-in has been declined. "
        "You can restart by saying 'resume'."
    ),
}


# ── SessionManager ─────────────────────────────────────────────────


class SessionManager:
    """Orchestrates the full message flow for a guest check-in session.

    Usage::

        sm = SessionManager()
        result = await sm.process_message(session_id, guest_msg, db)
    """

    def __init__(self) -> None:
        self._fallback = FallbackAgent()
        # LLM-powered components — initialised lazily
        self._llm_client: OllamaClient | None = None
        self._intent_detector: IntentDetector | None = None
        self._entity_extractor: EntityExtractor | None = None
        self._tool_router: ToolRouter | None = None

    def _ensure_llm(self) -> None:
        """Lazy-init LLM components so the app starts even if Ollama is down."""
        if self._llm_client is not None:
            return
        self._llm_client = OllamaClient(
            base_url=settings.OLLAMA_BASE_URL,
            model=settings.OLLAMA_MODEL,
        )
        self._intent_detector = IntentDetector(self._llm_client)
        self._entity_extractor = EntityExtractor(self._llm_client)
        self._tool_router = ToolRouter(tool_registry)

    # ── Public API ──────────────────────────────────────────────────

    async def process_message(
        self,
        session_id: str,
        guest_message: str,
        db: AsyncSession,
    ) -> dict[str, Any]:
        """Process a guest message through the full pipeline.

        Returns a dict with keys:
            agent_content, intent_detected, tools_called,
            current_state, required_action, session_status
        """
        # 1. Load session
        result = await db.execute(
            select(Session).where(Session.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            from app.state_machine.exceptions import SessionNotFoundError
            raise SessionNotFoundError(session_id)

        # 2. Get current state
        current_state = State(session.current_state)

        # 3. Detect intent (try Ollama, fallback to regex)
        intent_detected = await self._detect_intent(
            guest_message, current_state
        )

        # 4. Extract entities
        entities = await self._extract_entities(
            guest_message, current_state
        )

        # 5. Route to MCP tool (if applicable)
        tool_result, tools_called = await self._route_tool(
            intent_detected, entities, current_state, session_id, db
        )

        # 6. Advance state machine
        agent_content, current_state = await self._advance_state(
            session, current_state, intent_detected,
            guest_message, db, tool_result,
        )

        # 7. Generate state-aware response (for on-enter content)
        agent_content = self._enrich_response(
            agent_content, current_state, session, db
        )

        # 8. Save messages
        # Guest message
        guest_msg = Message(
            session_id=session.id,
            role="guest",
            content=guest_message,
        )
        db.add(guest_msg)
        await db.flush()

        # Agent response
        agent_msg = Message(
            session_id=session.id,
            role="agent",
            content=agent_content,
            intent_detected=intent_detected,
            tools_called=tools_called,
        )
        db.add(agent_msg)
        await db.flush()

        # Update last_message_at
        from datetime import datetime, timezone
        session.last_message_at = datetime.now(timezone.utc)

        # Refresh session to pick up state changes
        await db.refresh(session)

        required_action = get_required_action(current_state)

        return {
            "agent_content": agent_content,
            "intent_detected": intent_detected,
            "tools_called": tools_called,
            "current_state": current_state.value,
            "required_action": required_action,
            "session_status": session.status,
        }

    # ── Internal steps ──────────────────────────────────────────────

    async def _detect_intent(
        self, message: str, state: State
    ) -> str:
        """Detect intent via LLM, fall back to regex.

        If the LLM returns an intent that doesn't match a valid
        transition for the current state, try the regex fallback
        as it handles state-specific intents (start, confirm,
        upload_id, resume) that the LLM prompt doesn't cover.
        """
        self._ensure_llm()
        llm_intent: str | None = None
        try:
            assert self._intent_detector is not None
            llm_intent = await self._intent_detector.detect_intent(
                message, state
            )
            # If LLM intent is a valid transition, use it
            if llm_intent and can_transition(state, llm_intent):
                return llm_intent
            # If it's a question/greeting/request_help, those are
            # always valid (handled in the else branch of _advance_state)
            if llm_intent in ("question", "greeting", "request_help", "other"):
                return llm_intent
            # LLM intent doesn't match a valid transition — try regex
            logger.info(
                "LLM intent '%s' not valid for state %s, "
                "trying regex fallback",
                llm_intent, state.value,
            )
        except OllamaUnavailableError:
            logger.info(
                "Ollama unavailable, using regex fallback for intent"
            )
        except Exception as exc:
            logger.warning("LLM intent detection failed: %s", exc)

        # Regex fallback — handles state-specific intents
        regex_intent = self._fallback.detect_intent_regex(message, state)
        return regex_intent

    async def _extract_entities(
        self, message: str, state: State
    ) -> dict:
        """Extract entities via LLM, fall back to regex."""
        # Only extract for states that need it
        if state not in (
            State.INFO_VERIFY_PENDING,
            State.INCIDENTAL_PROTECTION_PENDING,
        ):
            return {}

        self._ensure_llm()
        try:
            assert self._entity_extractor is not None
            entities = await self._entity_extractor.extract_entities(
                message, state
            )
            return entities
        except OllamaUnavailableError:
            logger.info(
                "Ollama unavailable, using regex fallback for entities"
            )
        except Exception as exc:
            logger.warning("LLM entity extraction failed: %s", exc)

        # Regex fallback — use EntityExtractor's _extract_regex directly
        try:
            from app.agent.entity_extractor import EntityExtractor as _EE
            fallback_extractor = _EE(self._llm_client)
            return fallback_extractor._extract_regex(message, state)
        except Exception:
            return {}

    async def _route_tool(
        self,
        intent: str,
        entities: dict,
        state: State,
        session_id: str,
        db: AsyncSession,
    ) -> tuple[dict | None, list[str] | None]:
        """Route intent + entities to MCP tool if applicable.

        Returns (tool_result, tools_called).
        """
        self._ensure_llm()
        if self._tool_router is None:
            self._tool_router = ToolRouter(tool_registry)

        # Ensure registry is populated
        if not tool_registry.get_tool_names():
            tool_registry.register_all()

        # Only route for intents that have tool mappings
        if intent in ("question", "request_help", "greeting", "other"):
            # These don't route to tools via the tool_router
            return None, None

        try:
            result = await self._tool_router.route(
                intent=intent,
                entities=entities,
                state=state,
                session_id=session_id,
                db_session=db,
            )
            if result and "no_tool" in result:
                return None, None
            if result and "error" in result:
                logger.warning("Tool error: %s", result["error"])
                return result, None
            # Determine tool name from intent+state mapping
            from app.agent.tool_router import _INTENT_STATE_TOOL_MAP
            key = (intent, state)
            mapping = _INTENT_STATE_TOOL_MAP.get(key)
            tool_name = mapping["tool"] if mapping else "unknown"
            return result, [tool_name]
        except Exception as exc:
            logger.warning("Tool routing failed: %s", exc)
            return None, None

    async def _advance_state(
        self,
        session: Session,
        current_state: State,
        intent: str,
        guest_message: str,
        db: AsyncSession,
        tool_result: dict | None,
    ) -> tuple[str, State]:
        """Advance the state machine and generate a response.

        Returns (agent_content, new_state).
        """
        sm = StateMachine(db_session=db, session_id=session.id)
        agent_content = ""

        try:
            if intent == "decline" and can_transition(
                current_state, "decline"
            ):
                # Agreement refusal recording handled by ToolRouter (record_agreement tool)
                tools_called_decline: list[str] | None = None
                if agreement_type_for_state(current_state):
                    tools_called_decline = ["record_agreement"]

                new_state = await sm.decline(
                    guest_response=guest_message
                )
                agent_content = await self._enrich_state_content(
                    _STATE_RESPONSES.get(
                        new_state,
                        "Your check-in has been declined.",
                    ),
                    new_state,
                    session,
                    db,
                )
                current_state = new_state

            elif intent and can_transition(current_state, intent):
                # Agreement recording is handled by ToolRouter (record_agreement tool)
                # No need to create Agreement records here — the tool already did it

                new_state = await sm.advance(
                    intent, guest_response=guest_message
                )
                current_state = new_state

                # Generate on-enter content for the new state
                agent_content = await self._enrich_state_content(
                    _STATE_RESPONSES.get(
                        current_state,
                        get_required_action(current_state),
                    ),
                    current_state,
                    session,
                    db,
                )
            else:
                # Intent doesn't match valid transition
                required = get_required_action(current_state)

                if intent in ("question", "request_help"):
                    answer = await answer_question(
                        session, guest_message, db
                    )
                    if answer:
                        agent_content = answer
                    else:
                        agent_content = (
                            f"I don't have specific information about "
                            f"that, but I'm here to help with your "
                            f"check-in. {required}"
                        )
                elif intent == "greeting":
                    agent_content = (
                        f"Hello! Welcome to your check-in process. "
                        f"{required}"
                    )
                else:
                    agent_content = required

        except InvalidTransitionError as exc:
            agent_content = (
                f"I couldn't process that action right now. "
                f"Current step: {get_required_action(current_state)}"
            )
            logger.warning("Invalid transition attempt: %s", exc)

        return agent_content, current_state

    async def _enrich_state_content(
        self,
        template: str,
        state: State,
        session: Session,
        db: AsyncSession,
    ) -> str:
        """Enrich the state template with actual data from the reservation.

        For agreement states (PRIVACY_POLICY, HOUSE_RULES, RENTAL_AGREEMENT):
          append the full agreement text from the reservation.

        For INFO_VERIFY_PENDING:
          append the guest's name, email, phone, and number of guests.

        For other states: return the template as-is.
        """
        # Agreement states — append the full text
        agreement_type = agreement_type_for_state(state)
        if agreement_type:
            text = await _get_agreement_text(session, agreement_type, db)
            return f"{template}\n\n---\n\n{text}"

        # Info verify — append guest details
        if state == State.INFO_VERIFY_PENDING:
            reservation = await _fetch_reservation(session, db)
            guest = await _fetch_guest(session, db)
            if reservation and guest:
                info_lines = [
                    f"**Name:** {guest.first_name} {guest.last_name}",
                    f"**Email:** {guest.email or reservation.guest_email}",
                    f"**Phone:** {guest.phone or reservation.guest_phone or 'Not provided'}",
                    f"**Number of guests:** {reservation.num_guests}",
                    f"**Property:** {reservation.property_name}",
                    f"**Check-in:** {reservation.check_in_date}",
                    f"**Check-out:** {reservation.check_out_date}",
                ]
                info_block = "\n".join(info_lines)
                return f"{template}\n\n{info_block}"
            elif reservation:
                info_lines = [
                    f"**Name:** {reservation.guest_name}",
                    f"**Email:** {reservation.guest_email}",
                    f"**Phone:** {reservation.guest_phone or 'Not provided'}",
                    f"**Number of guests:** {reservation.num_guests}",
                    f"**Property:** {reservation.property_name}",
                    f"**Check-in:** {reservation.check_in_date}",
                    f"**Check-out:** {reservation.check_out_date}",
                ]
                info_block = "\n".join(info_lines)
                return f"{template}\n\n{info_block}"

        return template

    def _enrich_response(
        self,
        agent_content: str,
        current_state: State,
        session: Session,
        db: AsyncSession,
    ) -> str:
        """Enrich the agent response with state-specific content.

        - COMPLETED: include arrival instructions
        - ID_VERIFY_PENDING: include secure upload link
        - INCIDENTAL_PROTECTION_PENDING: include selection link
        """
        # For COMPLETED, arrival instructions are fetched async
        # at the endpoint level (since this method is sync).
        # We just use the template response here; the endpoint
        # can append instructions after calling process_message.
        return agent_content

    async def get_arrival_instructions(
        self, session_id: str, db: AsyncSession
    ) -> str | None:
        """Fetch rendered arrival instructions for a completed session."""
        handler = tool_registry.get_tool("get_arrival_instructions")
        if handler is None:
            return None
        try:
            result = await handler(
                db_session=db, session_id=session_id
            )
            if result and "instructions_html" in result:
                return result["instructions_html"]
        except Exception as exc:
            logger.warning("Failed to get arrival instructions: %s", exc)
        return None

    async def get_id_upload_link(
        self, session_id: str, db: AsyncSession
    ) -> str | None:
        """Fetch the ID upload link for a session."""
        handler = tool_registry.get_tool("generate_id_upload_link")
        if handler is None:
            return None
        try:
            result = await handler(
                db_session=db, session_id=session_id
            )
            if result and "upload_url" in result:
                return result["upload_url"]
        except Exception as exc:
            logger.warning("Failed to get ID upload link: %s", exc)
        return None

    async def get_incidental_link(
        self, session_id: str, db: AsyncSession
    ) -> str | None:
        """Fetch the incidental selection link for a session."""
        handler = tool_registry.get_tool("generate_incidental_link")
        if handler is None:
            return None
        try:
            result = await handler(
                db_session=db, session_id=session_id
            )
            if result and "selection_url" in result:
                return result["selection_url"]
        except Exception as exc:
            logger.warning(
                "Failed to get incidental link: %s", exc
            )
        return None
