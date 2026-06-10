"""State machine package — guest check-in workflow orchestration."""

from app.state_machine.audit import log_audit
from app.state_machine.exceptions import (
    ActionRequiredError,
    InvalidTransitionError,
    SessionNotFoundError,
)
from app.state_machine.machine import StateMachine
from app.state_machine.states import STATE_INFO, State
from app.state_machine.transitions import (
    VALID_TRANSITIONS,
    can_transition,
    get_next_state,
    get_required_action,
)

__all__ = [
    # Machine
    "StateMachine",
    # States
    "State",
    "STATE_INFO",
    # Transitions
    "can_transition",
    "get_next_state",
    "get_required_action",
    "VALID_TRANSITIONS",
    # Audit
    "log_audit",
    # Exceptions
    "InvalidTransitionError",
    "SessionNotFoundError",
    "ActionRequiredError",
]
