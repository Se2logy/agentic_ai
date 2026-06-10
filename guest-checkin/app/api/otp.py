"""OTP trigger and verification endpoints."""

import hmac
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session_token import get_session
from app.database import get_db
from app.models.otp_verification import OTPVerification
from app.models.session import Session
from app.schemas.otp import OTPVerifyRequest, OTPVerifyResponse
from app.services.email_service import email_service

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
    """
    # Get guest email from reservation
    reservation = session.reservation
    if reservation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reservation not found for this session",
        )

    guest_email = reservation.guest_email
    guest_name = reservation.guest_name

    # Generate 6-digit OTP using secrets (cryptographically secure)
    otp_code = "".join(
        [str(secrets.randbelow(10)) for _ in range(6)]
    )
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    # Create OTP verification record
    otp_record = OTPVerification(
        session_id=session.id,
        email=guest_email,
        otp_code=otp_code,
        verified=False,
        attempts=0,
        max_attempts=3,
        expires_at=expires_at,
    )
    db.add(otp_record)
    await db.flush()

    # Send OTP email
    sent = await email_service.send_otp_email(
        to_email=guest_email,
        otp_code=otp_code,
        guest_name=guest_name,
    )

    return {
        "message": "OTP sent" if sent else "OTP created but email delivery failed",
        "email": guest_email,
        "expires_at": expires_at.isoformat(),
    }


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

    Uses the session token for authentication. Checks the most recent
    unexpired OTP for the session.
    """
    now = datetime.now(timezone.utc)

    # Find the latest unexpired, unverified OTP for this session
    result = await db.execute(
        select(OTPVerification)
        .where(
            OTPVerification.session_id == session.id,
            OTPVerification.verified.is_(False),
            OTPVerification.expires_at > now,
        )
        .order_by(OTPVerification.created_at.desc())
    )
    otp_record = result.scalar_one_or_none()

    if otp_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active OTP found. Please trigger a new one.",
        )

    # Increment attempts
    otp_record.attempts += 1

    # Check max attempts
    if otp_record.attempts > otp_record.max_attempts:
        await db.flush()
        return OTPVerifyResponse(
            verified=False,
            attempts_remaining=0,
            message="Maximum attempts exceeded. Please trigger a new OTP.",
        )

    # Verify code (constant-time comparison to prevent timing attacks)
    if hmac.compare_digest(otp_record.otp_code, body.otp_code):
        otp_record.verified = True
        await db.flush()
        return OTPVerifyResponse(
            verified=True,
            attempts_remaining=otp_record.max_attempts - otp_record.attempts,
            message="OTP verified successfully.",
        )

    await db.flush()
    remaining = otp_record.max_attempts - otp_record.attempts
    return OTPVerifyResponse(
        verified=False,
        attempts_remaining=max(0, remaining),
        message=f"Invalid OTP code. {remaining} attempt(s) remaining.",
    )
