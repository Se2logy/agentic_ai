"""MCP tool: generate arrival instructions for a completed check-in."""

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)

TOOL_NAME = "get_arrival_instructions"
TOOL_DESCRIPTION = (
    "Generate formatted arrival instructions for the guest "
    "after they complete check-in. Includes property address, "
    "check-in/out dates, Wi-Fi details, lockbox code, and "
    "emergency contact. Use this when the check-in flow "
    "reaches the COMPLETED state."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
    },
    "required": ["session_id"],
}


async def get_arrival_instructions(
    db_session: AsyncSession, session_id: str
) -> dict[str, Any]:
    """Render arrival instructions HTML template with reservation data.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.

    Returns:
        Dict with rendered HTML instructions, or error.
    """
    if not session_id:
        return {"error": "session_id is required"}

    # Find session
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    # Find reservation via explicit query (avoid lazy-load on async)
    from app.models.reservation import Reservation

    stmt = select(Reservation).where(
        Reservation.id == session.reservation_id
    )
    result = await db_session.execute(stmt)
    reservation = result.scalar_one_or_none()

    if reservation is None:
        return {"error": f"Reservation not found for session: {session_id}"}

    # Find guest via explicit query (avoid lazy-load on async)
    from app.models.guest import Guest

    stmt = select(Guest).where(Guest.id == session.guest_id)
    result = await db_session.execute(stmt)
    guest = result.scalar_one_or_none()

    guest_name = (
        f"{guest.first_name} {guest.last_name}" if guest
        else reservation.guest_name
    )

    # Render template
    try:
        template = _jinja_env.get_template("arrival_instructions.html")
        html_content = template.render(
            guest_name=guest_name,
            property_name=reservation.property_name,
            property_address=reservation.property_address,
            check_in_date=str(reservation.check_in_date),
            check_out_date=str(reservation.check_out_date),
            num_guests=reservation.num_guests,
            wifi_network=reservation.wifi_network or "",
            wifi_password=reservation.wifi_password or "",
            lockbox_code=reservation.lockbox_code or "",
            emergency_contact=reservation.emergency_contact or "",
        )
    except Exception as exc:
        logger.exception(
            "Failed to render arrival instructions: session=%s", session_id
        )
        return {"error": f"Failed to render arrival instructions: {exc}"}

    logger.info("Arrival instructions generated: session=%s", session_id)

    return {
        "instructions_html": html_content,
        "property_name": reservation.property_name,
        "property_address": reservation.property_address,
        "check_in_date": str(reservation.check_in_date),
        "check_out_date": str(reservation.check_out_date),
        "guest_name": guest_name,
    }
