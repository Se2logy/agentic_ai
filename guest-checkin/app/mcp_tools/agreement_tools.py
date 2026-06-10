"""MCP tool: record guest acceptance or refusal of an agreement."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agreement import Agreement
from app.models.session import Session

logger = logging.getLogger(__name__)

VALID_AGREEMENT_TYPES = {"privacy_policy", "house_rules", "rental_agreement"}

TOOL_NAME = "record_agreement"
TOOL_DESCRIPTION = (
    "Record the guest's acceptance or refusal of an agreement. "
    "agreement_type must be one of: 'privacy_policy', 'house_rules', "
    "'rental_agreement'. accepted is True if the guest agrees, "
    "False if they decline. guest_response captures the guest's "
    "exact words. Use this when the guest explicitly agrees or "
    "declines an agreement presented during onboarding."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
        "agreement_type": {
            "type": "string",
            "description": (
                "Type of agreement: 'privacy_policy', "
                "'house_rules', or 'rental_agreement'."
            ),
        },
        "accepted": {
            "type": "boolean",
            "description": "True if guest accepts, False if guest declines.",
        },
        "guest_response": {
            "type": "string",
            "description": "The guest's exact response text.",
        },
    },
    "required": ["session_id", "agreement_type", "accepted"],
}


async def record_agreement(
    db_session: AsyncSession,
    session_id: str,
    agreement_type: str,
    accepted: bool,
    guest_response: str | None = None,
) -> dict[str, Any]:
    """Record a guest's agreement acceptance or refusal.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.
        agreement_type: One of privacy_policy/house_rules/rental_agreement.
        accepted: True if guest accepts, False if they decline.
        guest_response: The guest's exact response text (optional).

    Returns:
        Dict with confirmation details or error.
    """
    if not session_id:
        return {"error": "session_id is required"}

    if agreement_type not in VALID_AGREEMENT_TYPES:
        return {
            "error": f"Invalid agreement_type '{agreement_type}'. "
            f"Must be one of: {', '.join(sorted(VALID_AGREEMENT_TYPES))}"
        }

    # Verify session exists
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    agreement = Agreement(
        session_id=session_id,
        agreement_type=agreement_type,
        accepted=accepted,
        guest_response=guest_response,
    )
    db_session.add(agreement)
    await db_session.flush()

    logger.info(
        "Recorded agreement: session=%s type=%s accepted=%s",
        session_id,
        agreement_type,
        accepted,
    )

    return {
        "recorded": True,
        "agreement_id": agreement.id,
        "agreement_type": agreement_type,
        "accepted": accepted,
        "session_id": session_id,
    }
