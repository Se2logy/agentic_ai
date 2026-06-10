"""OTP trigger and verification endpoints — thin HTTP wrapper around otp_tools."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session_token import get_session
from app.database import get_db
from app.mcp_tools import otp_tools
from app.models.session import Session
from app.schemas.otp import OTPVerifyRequest, OTPVerifyResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["otp"])


@router.post(
    "/otp/trigger",
    summary="Trigger OTP for a session",
)
async def trigger_otp(
    session: Session = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate and send an OTP code to the guest's email.

    Uses the session token for authentication (Authorization: Bearer <token>).
    Delegates to otp_tools.trigger_otp for secure OTP generation and delivery.
    """
    result = await otp_tools.trigger_otp(db, session.id)

    if "error" in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    return result


@router.post(
    "/otp/verify",
    response_model=OTPVerifyResponse,
    summary="Verify OTP code",
)
async def verify_otp(
    body: OTPVerifyRequest,
    session: Session = Depends(get_session),
    db: AsyncSession = Depends(get_db),
) -> OTPVerifyResponse:
    """Verify an OTP code submitted by the guest.

    Uses the session token for authentication. Delegates to
    otp_tools.verify_otp for secure constant-time comparison.
    """
    result = await otp_tools.verify_otp(db, session.id, body.otp_code)

    # Map unrecoverable errors to HTTP 404 (no pending/expired OTP)
    if "error" in result and "attempts_remaining" not in result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    # Map expired OTP to 404 to match original API filtering
    if "error" in result and "expired" in result["error"].lower():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result["error"],
        )

    return OTPVerifyResponse(
        verified=result.get("verified", False),
        attempts_remaining=result.get("attempts_remaining", 0),
        message=_build_verify_message(result),
    )


def _build_verify_message(result: dict) -> str:
    """Build a user-friendly message from the verify_otp result dict."""
    if result.get("verified"):
        return "OTP verified successfully."

    error = result.get("error", "")
    remaining = result.get("attempts_remaining", 0)

    if "Maximum attempts" in error:
        return "Maximum attempts exceeded. Please trigger a new OTP."

    return f"Invalid OTP code. {remaining} attempt(s) remaining."
