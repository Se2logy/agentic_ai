"""Audit trail logging for state machine transitions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_trail import AuditTrail
from app.state_machine.states import State


async def log_audit(
    db_session: AsyncSession,
    session_id: str,
    action: str,
    from_state: State | None,
    to_state: State | None,
    details: dict | None = None,
    actor: str = "system",
) -> AuditTrail:
    """Create an AuditTrail record and add it to the session.

    The caller is responsible for committing the transaction
    (e.g. via an async context manager or explicit commit).

    Args:
        db_session: Async SQLAlchemy session.
        session_id: UUID of the check-in session.
        action: Description of the action (e.g. "advance", "decline").
        from_state: Previous state (None for session creation).
        to_state: New state (None for terminal actions).
        details: Optional JSON-serialisable dict with extra context.
        actor: Who initiated the action — "guest", "agent", or "system".

    Returns:
        The newly created AuditTrail ORM instance (not yet committed).
    """
    entry = AuditTrail(
        session_id=session_id,
        action=action,
        from_state=from_state.value if from_state is not None else None,
        to_state=to_state.value if to_state is not None else None,
        details=details,
        actor=actor,
    )
    db_session.add(entry)
    await db_session.flush()
    return entry
