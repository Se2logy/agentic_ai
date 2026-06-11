"""Pydantic schemas for incidental selection endpoints."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class IncidentalSelectRequest(BaseModel):
    """Request to select an incidental protection option."""

    selection_type: Literal["damage_waiver", "security_hold"] = Field(
        ...,
        description="Type of incidental protection: damage_waiver or security_hold",
    )


class IncidentalSelectResponse(BaseModel):
    """Response after selecting incidental protection and processing payment."""

    selection_type: str
    amount: Decimal
    payment_status: str
    payment_reference: str | None = None
    message: str
