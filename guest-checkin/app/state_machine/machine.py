"""StateMachine — orchestrates check-in state transitions with audit logging."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session
from app.state_machine.audit import log_audit
from app.state_machine.exceptions import (
    ActionRequiredError,
    InvalidTransitionError,
    SessionNotFoundError,
)
from app.state_machine.states import STATE_INFO, State
from app.state_machine.transitions import can_transition, get_next_state, get_required_action


class StateMachine:
    """Async state machine bound to a single check-in session.

    Every transition is validated against the transition table and
    logged to the audit trail. The session row in the database is
    updated on each state change.

    Usage::

        sm = StateMachine(db_session, session_id)
        new_state = await sm.advance("agree", guest_response="I accept")
    """

    def __init__(self, db_session: AsyncSession, session_id: str) -> None:
        self.db_session = db_session
        self.session_id = session_id

    # ── Internal helpers ────────────────────────────────────────────

    async def _load_session(self) -> Session:
        """Load the session row or raise SessionNotFoundError."""
        result = await self.db_session.execute(
            select(Session).where(Session.id == self.session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise SessionNotFoundError(self.session_id)
        return session

    async def _set_state(
        self,
        session: Session,
        new_state: State,
    ) -> None:
        """Persist a state change on the session row."""
        session.current_state = new_state.value

    async def _log_audit(
        self,
        action: str,
        from_state: State | None,
        to_state: State | None,
        details: dict | None = None,
        actor: str = "system",
    ) -> None:
        """Log a transition to the audit trail."""
        await log_audit(
            db_session=self.db_session,
            session_id=self.session_id,
            action=action,
            from_state=from_state,
            to_state=to_state,
            details=details,
            actor=actor,
        )

    # ── Public API ──────────────────────────────────────────────────

    async def advance(
        self,
        intent: str,
        guest_response: str | None = None,
    ) -> State:
        """Validate and execute a state transition.

        Args:
            intent: The detected guest intent (e.g. "agree", "decline").
            guest_response: Optional raw guest message for the audit trail.

        Returns:
            The new State after the transition.

        Raises:
            SessionNotFoundError: If the session does not exist.
            InvalidTransitionError: If the (current_state, intent) pair
                is not in the transition table.
        """
        session = await self._load_session()
        current_state = State(session.current_state)

        if not can_transition(current_state, intent):
            required = get_required_action(current_state)
            raise InvalidTransitionError(current_state.value, intent)

        new_state = get_next_state(current_state, intent)

        # Persist state change
        await self._set_state(session, new_state)

        # Audit trail
        details: dict = {"intent": intent}
        if guest_response is not None:
            details["guest_response"] = guest_response
        await self._log_audit(
            action="advance",
            from_state=current_state,
            to_state=new_state,
            details=details,
            actor="guest",
        )

        return new_state

    async def decline(self, guest_response: str | None = None) -> State:
        """Transition the session to REFUSED.

        This is a convenience method that records a guest's refusal
        at any agreement-pending state. The actual transition still
        goes through the transition table (intent="decline"), so it
        is only valid from states that allow it.

        Args:
            guest_response: Optional raw guest message explaining refusal.

        Returns:
            State.REFUSED

        Raises:
            InvalidTransitionError: If decline is not valid in the
                current state (e.g. COMPLETED).
        """
        session = await self._load_session()
        current_state = State(session.current_state)

        if not can_transition(current_state, "decline"):
            raise InvalidTransitionError(current_state.value, "decline")

        await self._set_state(session, State.REFUSED)

        details: dict = {"intent": "decline"}
        if guest_response is not None:
            details["guest_response"] = guest_response
        await self._log_audit(
            action="decline",
            from_state=current_state,
            to_state=State.REFUSED,
            details=details,
            actor="guest",
        )

        return State.REFUSED

    async def resume(self) -> State:
        """Reset a REFUSED session back to INIT so the guest can restart.

        Returns:
            State.INIT

        Raises:
            InvalidTransitionError: If the session is not in REFUSED.
        """
        session = await self._load_session()
        current_state = State(session.current_state)

        if not can_transition(current_state, "resume"):
            raise InvalidTransitionError(current_state.value, "resume")

        await self._set_state(session, State.INIT)

        await self._log_audit(
            action="resume",
            from_state=current_state,
            to_state=State.INIT,
            details={"intent": "resume"},
            actor="system",
        )

        return State.INIT

    async def get_current_state(self) -> tuple[State, str]:
        """Return the current state and its required action.

        Returns:
            A (State, required_action) tuple.

        Raises:
            SessionNotFoundError: If the session does not exist.
        """
        session = await self._load_session()
        current_state = State(session.current_state)
        required_action = get_required_action(current_state)
        return current_state, required_action
