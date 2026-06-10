"""Pydantic schemas for OTP verification endpoints."""

from pydantic import BaseModel, Field


class OTPVerifyRequest(BaseModel):
    """Request to verify an OTP code."""

    otp_code: str = Field(
        ...,
        min_length=1,
        max_length=10,
        description="The OTP code to verify",
    )


class OTPVerifyResponse(BaseModel):
    """Response after OTP verification attempt."""

    verified: bool
    attempts_remaining: int
    message: str
