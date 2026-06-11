"""MCP tools: generate incidental link and record incidental selection."""

import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incidental_selection import IncidentalSelection
from app.models.session import Session
from app.services.link_service import link_service
from app.services.payment_service import payment_service

logger = logging.getLogger(__name__)

INCIDENTAL_OPTIONS = [
    {
        "type": "damage_waiver",
        "amount": Decimal("49.00"),
        "description": (
            "Damage Waiver — covers up to $500 in accidental "
            "damages during your stay."
        ),
    },
    {
        "type": "security_hold",
        "amount": Decimal("250.00"),
        "description": (
            "Security Hold — $250 hold on your card, refunded "
            "within 7 days after check-out if no damage."
        ),
    },
]

# ── generate_incidental_link ────────────────────────────────────

GENERATE_TOOL_NAME = "generate_incidental_link"
GENERATE_TOOL_DESCRIPTION = (
    "Generate a secure, time-limited link for the guest to "
    "select an incidental protection option (Damage Waiver or "
    "Security Hold) and complete payment. Also returns the "
    "available options with descriptions. Use this when the "
    "guest reaches the incidental protection step."
)
GENERATE_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
    },
    "required": ["session_id"],
}


async def generate_incidental_link(
    db_session: AsyncSession, session_id: str
) -> dict[str, Any]:
    """Generate a secure link for incidental protection selection.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.

    Returns:
        Dict with selection_url and options, or error.
    """
    if not session_id:
        return {"error": "session_id is required"}

    # Verify session exists
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    token = link_service.generate_incidental_link(session_id)
    selection_url = f"/api/v1/incidental/{token}"

    logger.info("Incidental link generated: session=%s", session_id)

    return {
        "selection_url": selection_url,
        "expires_in": f"{link_service.expiry_hours} hour(s)",
        "options": INCIDENTAL_OPTIONS,
    }


# ── record_incidental_selection ─────────────────────────────────

RECORD_TOOL_NAME = "record_incidental_selection"
RECORD_TOOL_DESCRIPTION = (
    "Record the guest's incidental protection choice and "
    "process payment. selection_type must be 'damage_waiver' "
    "or 'security_hold'. Payment is processed via the payment "
    "gateway and an IncidentalSelection record is created. "
    "Use this when the guest selects an incidental option."
)
RECORD_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
        "selection_type": {
            "type": "string",
            "description": (
                "Type of incidental protection: "
                "'damage_waiver' or 'security_hold'."
            ),
        },
        "amount": {
            "type": "number",
            "description": "The amount for the selected option.",
        },
    },
    "required": ["session_id", "selection_type"],
}


async def record_incidental_selection(
    db_session: AsyncSession,
    session_id: str,
    selection_type: str,
    amount: Decimal | None = None,
) -> dict[str, Any]:
    """Record guest's incidental protection choice and process payment.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.
        selection_type: 'damage_waiver' or 'security_hold'.
        amount: The payment amount (defaults to standard price if not given).

    Returns:
        Dict with selection confirmation and payment details, or error.
    """
    if not session_id:
        return {"error": "session_id is required"}
    if not selection_type:
        return {"error": "selection_type is required"}

    valid_types = {opt["type"] for opt in INCIDENTAL_OPTIONS}
    if selection_type not in valid_types:
        return {
            "error": f"Invalid selection_type '{selection_type}'. "
            f"Must be one of: {', '.join(sorted(valid_types))}"
        }

    # Find session
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    # Resolve amount from defaults if not provided
    if amount is None:
        for opt in INCIDENTAL_OPTIONS:
            if opt["type"] == selection_type:
                amount = opt["amount"]
                break

    # Process payment
    payment_result = await payment_service.process_payment(
        guest_id=session.guest_id,
        amount=amount,
        description=f"Incidental protection: {selection_type}",
        metadata={"session_id": session_id, "selection_type": selection_type},
    )

    # Create IncidentalSelection record
    incidental = IncidentalSelection(
        session_id=session_id,
        selection_type=selection_type,
        amount=amount,
        payment_status="completed" if payment_result.success else "failed",
        payment_reference=payment_result.transaction_id,
    )
    db_session.add(incidental)
    await db_session.flush()

    logger.info(
        "Incidental selection recorded: session=%s type=%s amount=%.2f "
        "payment=%s",
        session_id,
        selection_type,
        amount,
        payment_result.transaction_id,
    )

    return {
        "selected": True,
        "selection_id": incidental.id,
        "selection_type": selection_type,
        "amount": amount,
        "payment": {
            "success": payment_result.success,
            "transaction_id": payment_result.transaction_id,
            "message": payment_result.message,
        },
    }
