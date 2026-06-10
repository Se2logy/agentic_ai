"""Pydantic schemas for session endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """Request to create a new check-in session."""

    booking_reference: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="The booking reference code for the reservation",
    )


class SessionResponse(BaseModel):
    """Response returned after creating or retrieving a session."""

    id: str
    reservation_id: str
    guest_id: str
    current_state: str
    session_token: str
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SessionStateResponse(BaseModel):
    """Response for the session state endpoint."""

    session_id: str
    current_state: str
    required_action: str
    status: str
