"""MCP tool: update guest personal information."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.guest import Guest
from app.models.session import Session

logger = logging.getLogger(__name__)

TOOL_NAME = "update_guest_info"
TOOL_DESCRIPTION = (
    "Update guest personal information during the info verification "
    "step. Provide the session_id and any fields that need updating: "
    "first_name, last_name, and/or phone. The guest record linked "
    "to the session will be updated. Use this when the guest corrects "
    "their name or phone number during onboarding."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
        "first_name": {
            "type": "string",
            "description": "Updated first name (optional).",
        },
        "last_name": {
            "type": "string",
            "description": "Updated last name (optional).",
        },
        "phone": {
            "type": "string",
            "description": "Updated phone number (optional).",
        },
    },
    "required": ["session_id"],
}


async def update_guest_info(
    db_session: AsyncSession,
    session_id: str,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    """Update guest personal information linked to a session.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.
        first_name: Updated first name (optional).
        last_name: Updated last name (optional).
        phone: Updated phone number (optional).

    Returns:
        Dict with updated guest info or error.
    """
    if not session_id:
        return {"error": "session_id is required"}

    if not any([first_name, last_name, phone]):
        return {"error": "At least one of first_name, last_name, or phone is required"}

    # Find session to get guest_id
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    # Find guest
    stmt = select(Guest).where(Guest.id == session.guest_id)
    result = await db_session.execute(stmt)
    guest = result.scalar_one_or_none()

    if guest is None:
        return {"error": f"Guest not found for session: {session_id}"}

    # Apply updates
    updated_fields = []
    if first_name is not None:
        guest.first_name = first_name
        updated_fields.append("first_name")
    if last_name is not None:
        guest.last_name = last_name
        updated_fields.append("last_name")
    if phone is not None:
        guest.phone = phone
        updated_fields.append("phone")

    await db_session.flush()

    logger.info(
        "Updated guest %s: fields=%s session=%s",
        guest.id,
        updated_fields,
        session_id,
    )

    return {
        "updated": True,
        "guest_id": guest.id,
        "updated_fields": updated_fields,
        "first_name": guest.first_name,
        "last_name": guest.last_name,
        "email": guest.email,
        "phone": guest.phone,
    }
