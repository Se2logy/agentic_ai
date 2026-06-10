"""Transition rules and validation for the state machine."""

from __future__ import annotations

from app.state_machine.exceptions import InvalidTransitionError
from app.state_machine.states import STATE_INFO, State

# ── Transition table ───────────────────────────────────────────────
# Maps (from_state, intent) → to_state.
# Each key represents a valid move; anything not listed is invalid.

VALID_TRANSITIONS: dict[tuple[State, str], State] = {
    # Start onboarding
    (State.INIT, "start"): State.PRIVACY_POLICY_PENDING,
    # Privacy policy
    (State.PRIVACY_POLICY_PENDING, "agree"): State.HOUSE_RULES_PENDING,
    (State.PRIVACY_POLICY_PENDING, "decline"): State.REFUSED,
    # House rules
    (State.HOUSE_RULES_PENDING, "agree"): State.RENTAL_AGREEMENT_PENDING,
    (State.HOUSE_RULES_PENDING, "decline"): State.REFUSED,
    # Rental agreement
    (State.RENTAL_AGREEMENT_PENDING, "agree"): State.INFO_VERIFY_PENDING,
    (State.RENTAL_AGREEMENT_PENDING, "decline"): State.REFUSED,
    # Info verification
    (State.INFO_VERIFY_PENDING, "confirm"): State.ID_VERIFY_PENDING,
    # (provide_info stays in same state so guest can correct and then confirm)
    (State.INFO_VERIFY_PENDING, "provide_info"): State.INFO_VERIFY_PENDING,
    # ID verification
    (State.ID_VERIFY_PENDING, "upload_id"): State.INCIDENTAL_PROTECTION_PENDING,
    # Incidental protection
    (
        State.INCIDENTAL_PROTECTION_PENDING,
        "select_option",
    ): State.COMPLETED,
    # Restart from refusal
    (State.REFUSED, "resume"): State.INIT,
}


def can_transition(current_state: State, intent: str) -> bool:
    """Return True if the (current_state, intent) pair is a valid transition."""
    return (current_state, intent) in VALID_TRANSITIONS


def get_next_state(current_state: State, intent: str) -> State:
    """Return the next state for a valid transition.

    Raises InvalidTransitionError if the (current_state, intent) pair
    is not in the transition table.
    """
    if (current_state, intent) in VALID_TRANSITIONS:
        return VALID_TRANSITIONS[(current_state, intent)]

    # COMPLETED is a terminal state — no transitions out
    if current_state == State.COMPLETED:
        raise InvalidTransitionError(current_state.value, intent)

    raise InvalidTransitionError(current_state.value, intent)


def get_required_action(current_state: State) -> str:
    """Return the human-readable required action for *current_state*."""
    info = STATE_INFO.get(current_state)
    if info is None:
        return "Unknown state"
    return str(info["required_action"])
