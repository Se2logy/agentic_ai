"""Session endpoints — create, retrieve, message, state, and resume."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.api_key import get_api_key
from app.auth.session_token import generate_session_token
from app.database import get_db
from app.models.api_key import APIKey
from app.models.audit_trail import AuditTrail
from app.models.guest import Guest
from app.models.message import Message
from app.models.reservation import Reservation
from app.models.session import Session
from app.schemas.message import AgentResponse, MessageResponse, SendMessageRequest
from app.schemas.session import CreateSessionRequest, SessionResponse, SessionStateResponse
from app.session_manager import SessionManager
from app.state_machine import InvalidTransitionError, SessionNotFoundError, StateMachine
from app.state_machine.states import State

logger = logging.getLogger(__name__)

router = APIRouter(tags=["sessions"])

# Singleton session manager — reuses LLM client across requests
_session_manager = SessionManager()


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new check-in session",
)
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> SessionResponse:
    """Create a new check-in session for a booking reference.

    Finds the reservation, creates a guest record if needed, and
    initialises a session in the INIT state.
    """
    # Look up reservation
    result = await db.execute(
        select(Reservation).where(
            Reservation.booking_reference == body.booking_reference
        )
    )
    reservation = result.scalar_one_or_none()
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Reservation not found for booking reference: {body.booking_reference}",
        )

    # Find or create guest
    result = await db.execute(
        select(Guest).where(Guest.email == reservation.guest_email)
    )
    guest = result.scalar_one_or_none()
    if guest is None:
        # Parse guest name
        name_parts = (reservation.guest_name or "").strip().split(" ", 1)
        first_name = name_parts[0] if name_parts else "Guest"
        last_name = name_parts[1] if len(name_parts) > 1 else ""
        guest = Guest(
            email=reservation.guest_email,
            first_name=first_name,
            last_name=last_name,
            phone=reservation.guest_phone,
        )
        db.add(guest)
        await db.flush()

    # Create session
    session_token = generate_session_token()
    session = Session(
        reservation_id=reservation.id,
        guest_id=guest.id,
        session_token=session_token,
        current_state="INIT",
        status="active",
    )
    db.add(session)
    await db.flush()

    # Refresh to load server-generated defaults (created_at, updated_at)
    await db.refresh(session)

    return SessionResponse.model_validate(session)


@router.get(
    "/sessions/{session_id}",
    response_model=SessionResponse,
    summary="Get session status",
)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> SessionResponse:
    """Retrieve a session by its ID."""
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    # Refresh to ensure lazy-loaded attributes are available
    await db.refresh(session)
    return SessionResponse.model_validate(session)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=AgentResponse,
    summary="Send a guest message and receive agent response",
)
async def send_message(
    session_id: str,
    body: SendMessageRequest,
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> AgentResponse:
    """Send a guest message, process through the SessionManager, and return the agent response.

    The SessionManager handles:
    1. Intent detection (Ollama LLM with regex fallback)
    2. Entity extraction
    3. MCP tool routing
    4. State machine advancement
    5. State-aware response generation
    6. Message persistence
    """
    try:
        result = await _session_manager.process_message(
            session_id=session_id,
            guest_message=body.content,
            db=db,
        )
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    except Exception as exc:
        logger.exception("Error processing message for session %s: %s", session_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again.",
        )

    # Enrich response with links/instructions for specific states
    current_state = State(result["current_state"])

    if current_state == State.COMPLETED:
        instructions = await _session_manager.get_arrival_instructions(
            session_id, db
        )
        if instructions:
            result["agent_content"] += f"\n\n{instructions}"

    elif current_state == State.ID_VERIFY_PENDING:
        upload_url = await _session_manager.get_id_upload_link(
            session_id, db
        )
        if upload_url:
            result["agent_content"] += f"\n\nSecure upload link: {upload_url}"

    elif current_state == State.INCIDENTAL_PROTECTION_PENDING:
        selection_url = await _session_manager.get_incidental_link(
            session_id, db
        )
        if selection_url:
            result["agent_content"] += f"\n\nSelection link: {selection_url}"

    # Build response — find the agent message that was just persisted
    # The SessionManager already saved the messages, so we need to
    # look up the latest agent message for this session.
    result_msg = await db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.role == "agent")
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    agent_msg = result_msg.scalar_one_or_none()

    # Re-load session to get current state
    result_sess = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result_sess.scalar_one_or_none()

    if agent_msg is None or session is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve processed message.",
        )

    # Refresh to ensure lazy-loaded attributes are available
    await db.refresh(agent_msg)

    # Update the persisted message with enriched content (links, instructions)
    # so the response includes the full content with appended links
    if agent_msg.content != result["agent_content"]:
        agent_msg.content = result["agent_content"]
        await db.flush()

    return AgentResponse(
        message=MessageResponse.model_validate(agent_msg),
        current_state=session.current_state,
        required_action=result["required_action"],
        session_status=session.status,
    )


@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageResponse],
    summary="Get message history",
)
async def get_messages(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> list[MessageResponse]:
    """Retrieve all messages for a session, ordered chronologically."""
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at.asc())
    )
    messages = result.scalars().all()
    # Refresh each message to ensure lazy-loaded attributes are available
    for m in messages:
        await db.refresh(m)
    return [MessageResponse.model_validate(m) for m in messages]


@router.get(
    "/sessions/{session_id}/state",
    response_model=SessionStateResponse,
    summary="Get current state machine state",
)
async def get_state(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> SessionStateResponse:
    """Return the current state and required action for a session."""
    sm = StateMachine(db_session=db, session_id=session_id)
    try:
        current_state, required_action = await sm.get_current_state()
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    # Load session for status
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one()

    return SessionStateResponse(
        session_id=session_id,
        current_state=current_state.value,
        required_action=required_action,
        status=session.status,
    )


@router.post(
    "/sessions/{session_id}/resume",
    response_model=SessionStateResponse,
    summary="Resume a REFUSED session",
)
async def resume_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> SessionStateResponse:
    """Restart a REFUSED session from the beginning (INIT state)."""
    sm = StateMachine(db_session=db, session_id=session_id)
    try:
        new_state = await sm.resume()
    except SessionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )
    except InvalidTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )

    # After resume, get the required action for INIT state
    from app.state_machine.transitions import get_required_action as _get_required_action

    required_action = _get_required_action(new_state)

    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one()

    return SessionStateResponse(
        session_id=session_id,
        current_state=new_state.value,
        required_action=required_action,
        status=session.status,
    )


@router.get(
    "/sessions/{session_id}/audit-trail",
    summary="Get audit trail for a session",
)
async def get_audit_trail(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    _api_key: APIKey = Depends(get_api_key),
) -> dict:
    """Retrieve the full audit trail for a session — every state transition,
    guest action, and system event with timestamps."""
    result = await db.execute(
        select(Session).where(Session.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session not found: {session_id}",
        )

    result = await db.execute(
        select(AuditTrail)
        .where(AuditTrail.session_id == session_id)
        .order_by(AuditTrail.created_at.asc())
    )
    entries = result.scalars().all()

    return {
        "session_id": session_id,
        "entries": [
            {
                "id": str(entry.id),
                "action": entry.action,
                "from_state": entry.from_state,
                "to_state": entry.to_state,
                "details": entry.details,
                "actor": entry.actor,
                "created_at": entry.created_at.isoformat() if entry.created_at else None,
            }
            for entry in entries
        ],
        "total": len(entries),
    }
