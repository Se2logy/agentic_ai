"""Seed reservations — 3 sample bookings with full data."""

import asyncio
import uuid
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.reservation import Reservation

PRIVACY_POLICY = (
    "We collect personal data (name, email, phone, ID document) solely to process "
    "your check-in and fulfil our contractual obligations as your accommodation "
    "provider. Your data is stored securely and will not be shared with third "
    "parties except where required by law. You may request deletion of your data "
    "after check-out by contacting privacy@guestapp.local."
)

HOUSE_RULES = (
    "1. No smoking inside the property.\n"
    "2. No parties or events without prior approval.\n"
    "3. Quiet hours: 22:00 – 08:00.\n"
    "4. Pets allowed only with prior arrangement.\n"
    "5. Please dispose of rubbish in the designated bins.\n"
    "6. Lock the door and return keys to the lockbox on departure.\n"
    "7. Report any damage immediately."
)

RENTAL_AGREEMENT = (
    "By accepting this agreement, the guest acknowledges that they have read and "
    "understood the house rules, cancellation policy, and liability terms. The guest "
    "agrees to pay for any damages caused during the stay beyond normal wear and "
    "tear. Check-in is after 15:00 and check-out is before 11:00 unless otherwise "
    "arranged."
)

RESERVATIONS = [
    {
        "booking_reference": "BK-2024-001",
        "property_name": "Seaside Cottage",
        "property_address": "12 Ocean Drive, Marina Bay, CA 90210",
        "guest_name": "Alice Johnson",
        "guest_email": "alice@example.com",
        "guest_phone": "+1-555-0101",
        "check_in_date": date(2024, 7, 1),
        "check_out_date": date(2024, 7, 7),
        "num_guests": 2,
        "wifi_network": "SeasideWiFi",
        "wifi_password": "ocean2024",
        "lockbox_code": "4482",
        "emergency_contact": "+1-555-0911",
        "house_rules_text": HOUSE_RULES,
        "rental_agreement_text": RENTAL_AGREEMENT,
        "privacy_policy_text": PRIVACY_POLICY,
    },
    {
        "booking_reference": "BK-2024-002",
        "property_name": "Mountain Lodge",
        "property_address": "45 Pine Trail, Summit Village, CO 80435",
        "guest_name": "Bob Smith",
        "guest_email": "bob@example.com",
        "guest_phone": "+1-555-0202",
        "check_in_date": date(2024, 8, 15),
        "check_out_date": date(2024, 8, 22),
        "num_guests": 4,
        "wifi_network": "LodgeNet",
        "wifi_password": "mountain24",
        "lockbox_code": "7719",
        "emergency_contact": "+1-555-0912",
        "house_rules_text": HOUSE_RULES,
        "rental_agreement_text": RENTAL_AGREEMENT,
        "privacy_policy_text": PRIVACY_POLICY,
    },
    {
        "booking_reference": "BK-2024-003",
        "property_name": "City Loft",
        "property_address": "88 Urban Street, Metro Center, NY 10001",
        "guest_name": "Carol Davis",
        "guest_email": "carol@example.com",
        "guest_phone": "+1-555-0303",
        "check_in_date": date(2024, 9, 5),
        "check_out_date": date(2024, 9, 10),
        "num_guests": 1,
        "wifi_network": "LoftConnect",
        "wifi_password": "cityloft24",
        "lockbox_code": "3305",
        "emergency_contact": "+1-555-0913",
        "house_rules_text": HOUSE_RULES,
        "rental_agreement_text": RENTAL_AGREEMENT,
        "privacy_policy_text": PRIVACY_POLICY,
    },
]


async def seed(session: AsyncSession | None = None) -> list[Reservation]:
    """Insert sample reservations. Uses provided session or creates one."""
    close = False
    if session is None:
        session = async_session_factory()
        close = True

    try:
        for data in RESERVATIONS:
            reservation = Reservation(**data)
            session.add(reservation)
        await session.commit()
        for r in session.new:
            pass  # objects are flushed after commit
        # re-query to return
        from sqlalchemy import select
        result = await session.execute(
            select(Reservation).where(
                Reservation.booking_reference.in_(
                    [d["booking_reference"] for d in RESERVATIONS]
                )
            )
        )
        return list(result.scalars().all())
    finally:
        if close:
            await session.close()


if __name__ == "__main__":
    asyncio.run(seed())
