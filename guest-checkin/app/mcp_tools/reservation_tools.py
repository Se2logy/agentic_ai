"""MCP tool: retrieve reservation details by booking reference."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation

logger = logging.getLogger(__name__)

TOOL_NAME = "get_reservation"
TOOL_DESCRIPTION = (
    "Retrieve reservation details by booking reference. "
    "Returns property name, guest info, check-in/out dates, "
    "Wi-Fi details, lockbox code, and agreement texts. "
    "Use this when the guest mentions their booking reference "
    "or when you need reservation details to present to the guest."
)
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "booking_reference": {
            "type": "string",
            "description": "The booking reference code (e.g. 'BK-2024-001').",
        },
    },
    "required": ["booking_reference"],
}


async def get_reservation(
    db_session: AsyncSession, booking_reference: str
) -> dict[str, Any] | None:
    """Look up a reservation by booking reference.

    Args:
        db_session: Async database session.
        booking_reference: The booking reference code.

    Returns:
        Dict with reservation details, or None if not found.
    """
    if not booking_reference or not booking_reference.strip():
        return {"error": "booking_reference is required"}

    stmt = select(Reservation).where(
        Reservation.booking_reference == booking_reference.strip()
    )
    result = await db_session.execute(stmt)
    reservation = result.scalar_one_or_none()

    if reservation is None:
        return None

    return {
        "id": reservation.id,
        "booking_reference": reservation.booking_reference,
        "property_name": reservation.property_name,
        "property_address": reservation.property_address,
        "guest_name": reservation.guest_name,
        "guest_email": reservation.guest_email,
        "guest_phone": reservation.guest_phone,
        "check_in_date": str(reservation.check_in_date),
        "check_out_date": str(reservation.check_out_date),
        "num_guests": reservation.num_guests,
        "wifi_network": reservation.wifi_network,
        "wifi_password": reservation.wifi_password,
        "lockbox_code": reservation.lockbox_code,
        "emergency_contact": reservation.emergency_contact,
        "privacy_policy_text": reservation.privacy_policy_text,
        "house_rules_text": reservation.house_rules_text,
        "rental_agreement_text": reservation.rental_agreement_text,
    }
