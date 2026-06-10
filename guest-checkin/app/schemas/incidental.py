"""Pydantic schemas for incidental selection endpoints."""

from pydantic import BaseModel, Field


class IncidentalSelectRequest(BaseModel):
    """Request to select an incidental protection option."""

    selection_type: str = Field(
        ...,
        description="Type of incidental protection: damage_waiver or security_hold",
    )


class IncidentalSelectResponse(BaseModel):
    """Response after selecting incidental protection and processing payment."""

    selection_type: str
    amount: float
    payment_status: str
    payment_reference: str | None = None
    message: str
