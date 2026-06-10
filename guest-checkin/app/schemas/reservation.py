"""Pydantic schemas for reservation endpoints."""

from datetime import date, datetime

from pydantic import BaseModel


class ReservationResponse(BaseModel):
    """Full reservation details returned to platform integrators."""

    id: str
    booking_reference: str
    property_name: str
    property_address: str
    guest_name: str
    guest_email: str
    guest_phone: str | None = None
    check_in_date: date
    check_out_date: date
    num_guests: int = 1
    wifi_network: str | None = None
    wifi_password: str | None = None
    lockbox_code: str | None = None
    emergency_contact: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}
