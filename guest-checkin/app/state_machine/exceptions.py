"""Custom exceptions for the state machine."""


class InvalidTransitionError(Exception):
    """Raised when a state transition is not allowed."""

    def __init__(self, current_state: str, intent: str) -> None:
        self.current_state = current_state
        self.intent = intent
        super().__init__(
            f"Invalid transition: cannot apply intent '{intent}' "
            f"from state '{current_state}'"
        )


class SessionNotFoundError(Exception):
    """Raised when a session ID does not exist in the database."""

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        super().__init__(f"Session not found: {session_id}")


class ActionRequiredError(Exception):
    """Raised when a guest tries to advance without completing the required action."""

    def __init__(self, current_state: str, required_action: str) -> None:
        self.current_state = current_state
        self.required_action = required_action
        super().__init__(
            f"Action required before advancing: {required_action} "
            f"(current state: {current_state})"
        )
