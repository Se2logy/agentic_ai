"""PromptBuilder — constructs the LLM system prompt based on current state."""

from __future__ import annotations

import json

from app.state_machine.states import STATE_INFO, State


class PromptBuilder:
    """Builds state-aware system prompts for the LLM agent."""

    # Agent persona — included in every system prompt
    _PERSONA = (
        "You are a friendly and professional guest check-in assistant for "
        "a vacation rental property. Your role is to guide guests through "
        "the check-in process step by step. Be concise, warm, and clear. "
        "Always confirm the guest's action before proceeding."
    )

    # State-specific instructions
    _STATE_INSTRUCTIONS: dict[State, str] = {
        State.INIT: (
            "The check-in session has just been created. Greet the guest "
            "warmly and invite them to begin the onboarding process."
        ),
        State.PRIVACY_POLICY_PENDING: (
            "The guest needs to accept the Privacy Policy & Data Usage "
            "agreement. Present the privacy policy and ask for their "
            "acceptance. If they have questions, answer them clearly. "
            "If they decline, let them know check-in cannot proceed."
        ),
        State.HOUSE_RULES_PENDING: (
            "The guest needs to accept the House Rules. Present the house "
            "rules and ask for their acceptance. If they have questions, "
            "answer them. If they decline, explain the consequences."
        ),
        State.RENTAL_AGREEMENT_PENDING: (
            "The guest needs to accept the Rental Agreement. Present the "
            "rental agreement and ask for their acceptance. If they have "
            "questions, answer them. If they decline, explain the consequences."
        ),
        State.INFO_VERIFY_PENDING: (
            "The guest needs to verify their personal information (name, "
            "email, phone). Present the information we have on file and "
            "ask them to confirm or provide corrections. If they say the "
            "info is correct, trigger OTP verification. If they provide "
            "updated info, update their record and ask them to confirm again."
        ),
        State.ID_VERIFY_PENDING: (
            "The guest needs to upload a government-issued ID. Generate "
            "a secure upload link and send it to them. Explain what "
            "documents are accepted (passport, driver's license, etc.)."
        ),
        State.INCIDENTAL_PROTECTION_PENDING: (
            "The guest needs to select an incidental protection option. "
            "Present the two choices:\n"
            "1. Damage Waiver ($49) — covers up to $500 in accidental "
            "damages during the stay.\n"
            "2. Security Hold ($250) — held on the card and refunded "
            "within 7 days after check-out if no damage.\n"
            "Ask them to choose one and complete payment."
        ),
        State.COMPLETED: (
            "The guest has completed all check-in steps. Congratulate "
            "them and provide arrival instructions."
        ),
        State.REFUSED: (
            "The guest declined an agreement and check-in is halted. "
            "Offer to restart the process or connect them with support."
        ),
    }

    # FAQ-style responses for common questions
    _FAQ_RESPONSES = (
        "\nCommon questions and how to answer them:\n"
        "- 'What is the damage waiver?' → A $49 fee that covers up to "
        "$500 in accidental damages.\n"
        "- 'What is the security hold?' → A $250 hold on your card, "
        "refunded within 7 days if no damage.\n"
        "- 'Is my data safe?' → Yes, we follow strict data privacy "
        "practices as outlined in the Privacy Policy.\n"
        "- 'How long does check-in take?' → Typically 5–10 minutes.\n"
        "- 'What ID do I need?' → Any government-issued photo ID "
        "(passport, driver's license, national ID).\n"
        "- 'Can I skip a step?' → All steps are required to complete "
        "check-in.\n"
    )

    _CONVERSATION_GUIDELINES = (
        "\nConversation guidelines:\n"
        "- Be warm but professional.\n"
        "- Keep responses concise (2–3 sentences unless explaining).\n"
        "- Always acknowledge the guest's input before acting.\n"
        "- If the guest asks something unrelated, gently redirect.\n"
        "- If unsure, offer to connect them with a human agent.\n"
    )

    def build_system_prompt(
        self,
        state: State,
        session_context: dict,
    ) -> str:
        """Build the system prompt for the current state.

        Args:
            state: The current state machine state.
            session_context: Additional context (session_id, guest info, etc.).

        Returns:
            The complete system prompt string.
        """
        parts: list[str] = [self._PERSONA]

        # Current state
        state_info = STATE_INFO.get(state, {})
        required_action = state_info.get("required_action", "Unknown")
        parts.append(
            f"\nCurrent state: {state.value}\n"
            f"Required action: {required_action}"
        )

        # State-specific instructions
        instructions = self._STATE_INSTRUCTIONS.get(state, "")
        if instructions:
            parts.append(f"\n{instructions}")

        # Session context (guest name, booking ref, etc.)
        if session_context:
            context_lines = []
            if "guest_name" in session_context:
                context_lines.append(f"Guest name: {session_context['guest_name']}")
            if "booking_reference" in session_context:
                context_lines.append(
                    f"Booking reference: {session_context['booking_reference']}"
                )
            if "property_name" in session_context:
                context_lines.append(
                    f"Property: {session_context['property_name']}"
                )
            if context_lines:
                parts.append("\n" + "\n".join(context_lines))

        # FAQ
        parts.append(self._FAQ_RESPONSES)

        # Conversation guidelines
        parts.append(self._CONVERSATION_GUIDELINES)

        return "\n".join(parts)

    def build_tool_descriptions_section(
        self, tool_descriptions: list[dict]
    ) -> str:
        """Format tool descriptions for inclusion in the system prompt.

        Args:
            tool_descriptions: Output of ToolRegistry.get_tool_descriptions().

        Returns:
            A formatted string listing available tools.
        """
        if not tool_descriptions:
            return "\nAvailable tools: none"

        lines = ["\nAvailable tools:"]
        for tool in tool_descriptions:
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            params = tool.get("parameters", {}).get("properties", {})
            param_names = list(params.keys())
            lines.append(f"- {name}({', '.join(param_names)}): {desc}")

        return "\n".join(lines)
