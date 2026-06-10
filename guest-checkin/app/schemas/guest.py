"""Pydantic schemas for guest info updates."""

from pydantic import BaseModel, Field


class GuestInfoUpdate(BaseModel):
    """Request to update guest personal information."""

    first_name: str | None = Field(None, max_length=255)
    last_name: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=50)
