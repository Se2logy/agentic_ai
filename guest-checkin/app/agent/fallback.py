"""FallbackAgent — regex-based intent detection and template responses.

Used when the Ollama LLM service is completely unavailable.
"""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.state_machine.states import STATE_INFO, State
from app.utils import agreement_type_for_state, answer_question


class FallbackAgent:
    """Regex-based fallback for intent detection and response generation."""

    # ── Intent detection ─────────────────────────────────────────────

    # Intent keywords — ordered from most specific to least.
    # Decline MUST come before agree so "don't agree" / "refuse to accept"
    # are caught as decline before "agree"/"accept" triggers agree.
    # request_help MUST come before question so "I need help" wins over "can I".
    _INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
        ("decline", re.compile(
            r"\b(don'?t\s+agree|don'?t\s+accept|i\s+decline|i\s+refuse|"
            r"decline|disagree|reject|refuse|nope|no)\b",
            re.IGNORECASE,
        )),
        ("request_help", re.compile(
            r"\b(i\s+need\s+help|help\s+me|assist|support|agent|human|"
            r"speak\s+to\s+someone|talk\s+to\s+someone|someone\s+help)\b",
            re.IGNORECASE,
        )),
        ("select_option", re.compile(
            r"\b(damage\s*waiver|security\s*hold|option\s*(1|2|one|two)|first\s+option|second\s+option)\b",
            re.IGNORECASE,
        )),
        ("provide_info", re.compile(
            r"\b(my\s+(name|phone|email|number)\s+is|call\s+me|i'?m\s+\w+|this\s+is|update|change)\b",
            re.IGNORECASE,
        )),
        ("question", re.compile(
            r"\b(what|when|where|who|how|why|is\s+it|do\s+you|are\s+there)\b|\?",
            re.IGNORECASE,
        )),
        ("agree", re.compile(
            r"\b(yes|yeah|yep|agree|accept|okay|ok|sure|i\s+do|i\s+accept|i\s+agree|correct|confirmed)\b",
            re.IGNORECASE,
        )),
        ("greeting", re.compile(
            r"\b(hi|hello|hey|good\s+(morning|afternoon|evening)|greetings)\b",
            re.IGNORECASE,
        )),
    ]

    def detect_intent_regex(self, message: str, state: State) -> str:
        """Detect intent from a user message using regex patterns.

        State-aware adjustments:
        - In INIT, "start/begin/ready" → "start"
        - In INFO_VERIFY_PENDING, "correct/confirmed" → "confirm"
        - In ID_VERIFY_PENDING, "uploaded/sent id" → "upload_id"
        - In INCIDENTAL_PROTECTION_PENDING, specific options → "select_option"
        - In REFUSED, "resume/restart" → "resume"

        Args:
            message: The guest's message text.
            state: The current state machine state.

        Returns:
            One of: start, agree, decline, confirm, upload_id,
            select_option, resume, question, provide_info,
            request_help, greeting, other.
        """
        # State-specific overrides first
        if state == State.INIT:
            if re.search(
                r"\b(start|begin|let'?s\s+(start|begin|go|check\s*in)|ready|i'?m\s+ready)\b",
                message, re.IGNORECASE,
            ):
                return "start"

        if state == State.INFO_VERIFY_PENDING:
            if re.search(
                r"\b(confirm|correct|confirmed|looks\s+good|that'?s\s+right|that'?s\s+correct|verified|yes)\b",
                message, re.IGNORECASE,
            ):
                return "confirm"

        if state == State.ID_VERIFY_PENDING:
            if re.search(
                r"\b(uploaded|sent\s+id|done\s+uploading|id\s+uploaded|upload\s+complete|finished\s+uploading)\b",
                message, re.IGNORECASE,
            ):
                return "upload_id"

        if state == State.INCIDENTAL_PROTECTION_PENDING:
            if re.search(r"\b(damage\s*waiver)\b", message, re.IGNORECASE):
                return "select_option"
            if re.search(r"\b(security\s*hold)\b", message, re.IGNORECASE):
                return "select_option"

        if state == State.REFUSED:
            if re.search(r"\b(resume|restart|try\s+again|start\s+over)\b", message, re.IGNORECASE):
                return "resume"

        # General pattern matching
        for intent, pattern in self._INTENT_PATTERNS:
            if pattern.search(message):
                return intent

        return "other"

    # ── Response generation ──────────────────────────────────────────

    _AGREEMENT_STATE_TEMPLATES: dict[State, dict[str, str]] = {
        State.PRIVACY_POLICY_PENDING: {
            "agree": (
                "Thank you for accepting the Privacy Policy & Data Usage "
                "agreement. Let's move on to the House Rules."
            ),
            "decline": (
                "We're sorry you declined the Privacy Policy. Unfortunately, "
                "we cannot proceed with check-in without your acceptance. "
                "You can restart the process at any time."
            ),
            "question": (
                "I'd be happy to help with your question about the Privacy "
                "Policy. Could you please specify what you'd like to know?"
            ),
        },
        State.HOUSE_RULES_PENDING: {
            "agree": (
                "Thank you for accepting the House Rules. Now let's review "
                "the Rental Agreement."
            ),
            "decline": (
                "We're sorry you declined the House Rules. Unfortunately, "
                "we cannot proceed with check-in without your acceptance. "
                "You can restart the process at any time."
            ),
            "question": (
                "I'd be happy to help with your question about the House "
                "Rules. Could you please specify what you'd like to know?"
            ),
        },
        State.RENTAL_AGREEMENT_PENDING: {
            "agree": (
                "Thank you for accepting the Rental Agreement. Now let's "
                "verify your personal information."
            ),
            "decline": (
                "We're sorry you declined the Rental Agreement. Unfortunately, "
                "we cannot proceed with check-in without your acceptance. "
                "You can restart the process at any time."
            ),
            "question": (
                "I'd be happy to help with your question about the Rental "
                "Agreement. Could you please specify what you'd like to know?"
            ),
        },
    }

    _STATE_TEMPLATES: dict[State, dict[str, str]] = {
        State.INIT: {
            "greeting": "Welcome! I'm here to help you check in. Let's get started!",
            "other": "Welcome! Please say 'start' to begin the check-in process.",
        },
        State.INFO_VERIFY_PENDING: {
            "agree": (
                "Great, your information has been confirmed! Let's move on to "
                "ID verification. I'll generate a secure upload link for you."
            ),
            "provide_info": (
                "Thank you for providing your updated information. I've noted "
                "the changes. Please confirm when the details are correct."
            ),
            "question": (
                "I'd be happy to help with your question. Could you please "
                "specify what you'd like to know about your information?"
            ),
        },
        State.ID_VERIFY_PENDING: {
            "agree": (
                "I've generated a secure link for you to upload your "
                "government-issued ID. Please use the link to complete "
                "the upload."
            ),
            "question": (
                "For ID verification, you'll need a government-issued photo ID "
                "such as a passport or driver's license. I'll send you a "
                "secure link to upload it."
            ),
        },
        State.INCIDENTAL_PROTECTION_PENDING: {
            "select_option": (
                "Thank you for selecting your incidental protection option. "
                "Your choice has been recorded and payment is being processed."
            ),
            "question": (
                "You have two options for incidental protection:\n"
                "1. Damage Waiver ($49.00) — covers up to $500 in accidental "
                "damages.\n"
                "2. Security Hold ($250) — held on your card and refunded "
                "within 7 days if no damage occurs.\n"
                "Which would you prefer?"
            ),
        },
        State.COMPLETED: {
            "other": (
                "Your check-in is complete! You'll receive arrival "
                "instructions shortly. Have a wonderful stay!"
            ),
        },
        State.REFUSED: {
            "other": (
                "Your check-in was paused because an agreement was declined. "
                "If you'd like to restart, please let me know."
            ),
            "request_help": (
                "I understand you'd like assistance. A member of our team "
                "will reach out to you shortly to help with your check-in."
            ),
        },
    }

    def generate_response(
        self,
        intent: str,
        state: State,
        tool_result: dict | None = None,
    ) -> str:
        """Generate a template response for a state and intent combination.

        Args:
            intent: The detected intent string.
            state: The current state machine state.
            tool_result: Optional result from a tool call to include.

        Returns:
            A human-readable response string.
        """
        # Check agreement states first
        if state in self._AGREEMENT_STATE_TEMPLATES:
            templates = self._AGREEMENT_STATE_TEMPLATES[state]
            if intent in templates:
                return self._maybe_append_tool_result(templates[intent], tool_result)

        # Check general state templates
        if state in self._STATE_TEMPLATES:
            templates = self._STATE_TEMPLATES[state]
            if intent in templates:
                return self._maybe_append_tool_result(templates[intent], tool_result)

        # Default fallback — describe what the guest needs to do
        info = STATE_INFO.get(state)
        if info:
            required = info.get("required_action", "")
            return (
                f"I'm here to help with your check-in. "
                f"Currently, you need to: {required}. "
                f"Could you please respond accordingly?"
            )

        return (
            "I'm sorry, I didn't understand that. "
            "Could you please rephrase your request?"
        )

    # ── Full message processing (used by WebSocket handler) ──────────

    async def process_message(
        self,
        session: "Session",
        guest_content: str,
        db: "AsyncSession",
    ) -> tuple[str, str | None, list[str] | None, str, str]:
        """Process a guest message end-to-end: detect intent, advance
        state machine, call tools, generate response.

        Returns:
            (agent_content, intent_detected, tools_called,
             current_state_value, required_action)
        """
        from app.state_machine import InvalidTransitionError, StateMachine
        from app.state_machine.transitions import can_transition, get_required_action

        current_state = State(session.current_state)
        intent = self.detect_intent_regex(guest_content, current_state)
        intent_detected: str | None = intent
        tools_called: list[str] | None = None
        agent_content = ""

        sm = StateMachine(db_session=db, session_id=session.id)

        try:
            if intent == "decline" and can_transition(current_state, "decline"):
                agreement_type = agreement_type_for_state(current_state)
                if agreement_type:
                    from app.models.agreement import Agreement

                    agreement = Agreement(
                        session_id=session.id,
                        agreement_type=agreement_type,
                        accepted=False,
                        guest_response=guest_content,
                    )
                    db.add(agreement)
                    await db.flush()
                    tools_called = ["record_agreement"]

                new_state = await sm.decline(guest_response=guest_content)
                agent_content = self.generate_response("decline", new_state)
                current_state = new_state

            elif intent and can_transition(current_state, intent):
                agreement_type = agreement_type_for_state(current_state)
                if agreement_type and intent == "agree":
                    from app.models.agreement import Agreement

                    agreement = Agreement(
                        session_id=session.id,
                        agreement_type=agreement_type,
                        accepted=True,
                        guest_response=guest_content,
                    )
                    db.add(agreement)
                    await db.flush()
                    tools_called = ["record_agreement"]

                new_state = await sm.advance(intent, guest_response=guest_content)
                current_state = new_state
                agent_content = self.generate_response(intent, current_state)

            else:
                # Intent doesn't match a valid transition
                required = get_required_action(current_state)

                if intent in ("question", "request_help"):
                    answer = await answer_question(session, guest_content, db)
                    if answer:
                        agent_content = answer
                    else:
                        agent_content = self.generate_response(intent, current_state)
                elif intent == "greeting":
                    agent_content = self.generate_response("greeting", current_state)
                else:
                    agent_content = self.generate_response("other", current_state)

        except InvalidTransitionError as exc:
            agent_content = (
                f"I couldn't process that action right now. "
                f"Current step: {get_required_action(current_state)}"
            )
            import logging
            logging.getLogger(__name__).warning("Invalid transition attempt: %s", exc)

        required_action = get_required_action(current_state)
        return (
            agent_content,
            intent_detected,
            tools_called,
            current_state.value,
            required_action,
        )

    def _maybe_append_tool_result(
        self, template: str, tool_result: dict | None
    ) -> str:
        """Append tool result info to a template response if available."""
        if tool_result and "error" in tool_result:
            return f"{template}\n\nNote: There was an issue — {tool_result['error']}."
        return template

