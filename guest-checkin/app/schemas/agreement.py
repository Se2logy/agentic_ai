"""Pydantic schemas for agreement records."""

from datetime import datetime

from pydantic import BaseModel, Field


class AgreementRecord(BaseModel):
    """Record of a guest's acceptance or refusal of an agreement."""

    id: str | None = None
    session_id: str
    agreement_type: str = Field(
        ...,
        description="Type of agreement: privacy_policy, house_rules, rental_agreement",
    )
    accepted: bool = Field(..., description="Whether the guest accepted")
    guest_response: str | None = Field(None, description="Raw guest response text")
    created_at: datetime | None = None

    model_config = {"from_attributes": True}
