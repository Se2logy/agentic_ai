"""MCP tools: trigger and verify OTP for guest identity verification."""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.otp_verification import OTPVerification
from app.models.session import Session
from app.services.email_service import email_service

logger = logging.getLogger(__name__)

OTP_EXPIRY_MINUTES = 10
OTP_CODE_LENGTH = 6

# ── trigger_otp ──────────────────────────────────────────────────

TRIGGER_TOOL_NAME = "trigger_otp"
TRIGGER_TOOL_DESCRIPTION = (
    "Generate and send a 6-digit OTP code to the guest's email "
    "for identity verification. The code expires in 10 minutes "
    "and allows up to 3 verification attempts. Use this when "
    "the guest needs to verify their email during the "
    "info verification step."
)
TRIGGER_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
    },
    "required": ["session_id"],
}


async def trigger_otp(
    db_session: AsyncSession, session_id: str
) -> dict[str, Any]:
    """Generate an OTP, save it, and email it to the guest.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.

    Returns:
        Dict with otp_sent status and masked email, or error.
    """
    if not session_id:
        return {"error": "session_id is required"}

    # Find session
    stmt = select(Session).where(Session.id == session_id)
    result = await db_session.execute(stmt)
    session = result.scalar_one_or_none()

    if session is None:
        return {"error": f"Session not found: {session_id}"}

    # Find guest via explicit query (avoid lazy-load on async session)
    from app.models.guest import Guest

    stmt = select(Guest).where(Guest.id == session.guest_id)
    result = await db_session.execute(stmt)
    guest = result.scalar_one_or_none()

    if guest is None:
        return {"error": f"Guest not found for session: {session_id}"}

    # Generate 6-digit OTP using secrets (cryptographically secure)
    otp_code = "".join(
        [str(secrets.randbelow(10)) for _ in range(OTP_CODE_LENGTH)]
    )
    expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=OTP_EXPIRY_MINUTES
    )

    # Create OTPVerification record
    otp_record = OTPVerification(
        session_id=session_id,
        email=guest.email,
        otp_code=otp_code,
        verified=False,
        attempts=0,
        max_attempts=3,
        expires_at=expires_at,
    )
    db_session.add(otp_record)
    await db_session.flush()

    # Send OTP email
    email_sent = await email_service.send_otp_email(
        to_email=guest.email,
        otp_code=otp_code,
        guest_name=guest.first_name,
    )

    if not email_sent:
        logger.warning("OTP email failed for session=%s", session_id)
        return {
            "otp_sent": False,
            "error": "Failed to send OTP email",
            "email": _mask_email(guest.email),
        }

    logger.info(
        "OTP triggered: session=%s email=%s expires=%s",
        session_id,
        _mask_email(guest.email),
        expires_at.isoformat(),
    )

    return {
        "otp_sent": True,
        "email": _mask_email(guest.email),
        "expires_in": f"{OTP_EXPIRY_MINUTES} minutes",
    }


# ── verify_otp ──────────────────────────────────────────────────

VERIFY_TOOL_NAME = "verify_otp"
VERIFY_TOOL_DESCRIPTION = (
    "Verify a 6-digit OTP code entered by the guest. "
    "Checks that the code matches, has not expired, and "
    "attempts have not been exceeded. Returns whether "
    "verified and remaining attempts. Use this after "
    "trigger_otp when the guest provides their code."
)
VERIFY_TOOL_PARAMETERS = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "The current check-in session ID.",
        },
        "otp_code": {
            "type": "string",
            "description": "The 6-digit OTP code entered by the guest.",
        },
    },
    "required": ["session_id", "otp_code"],
}


async def verify_otp(
    db_session: AsyncSession, session_id: str, otp_code: str
) -> dict[str, Any]:
    """Verify an OTP code submitted by the guest.

    Args:
        db_session: Async database session.
        session_id: The check-in session ID.
        otp_code: The 6-digit code the guest entered.

    Returns:
        Dict with verified status and attempts_remaining, or error.
    """
    if not session_id:
        return {"error": "session_id is required"}
    if not otp_code:
        return {"error": "otp_code is required"}

    # Find the latest unverified OTP for this session
    stmt = (
        select(OTPVerification)
        .where(
            OTPVerification.session_id == session_id,
            OTPVerification.verified == False,  # noqa: E712
        )
        .order_by(OTPVerification.created_at.desc())
    )
    result = await db_session.execute(stmt)
    otp_record = result.scalar_one_or_none()

    if otp_record is None:
        return {
            "verified": False,
            "error": "No pending OTP found. Please trigger a new OTP.",
        }

    # Check if already expired
    now = datetime.now(timezone.utc)
    if now > otp_record.expires_at.replace(tzinfo=timezone.utc):
        return {
            "verified": False,
            "error": "OTP has expired. Please trigger a new OTP.",
            "attempts_remaining": 0,
        }

    # Check attempts
    otp_record.attempts += 1
    attempts_remaining = otp_record.max_attempts - otp_record.attempts

    if otp_record.attempts > otp_record.max_attempts:
        await db_session.flush()
        return {
            "verified": False,
            "error": "Maximum attempts exceeded. Please trigger a new OTP.",
            "attempts_remaining": 0,
        }

    # Check code match (constant-time comparison to prevent timing attacks)
    if not hmac.compare_digest(otp_record.otp_code, otp_code):
        await db_session.flush()
        return {
            "verified": False,
            "error": "Invalid OTP code.",
            "attempts_remaining": attempts_remaining,
        }

    # Success
    otp_record.verified = True
    await db_session.flush()

    logger.info("OTP verified: session=%s", session_id)

    return {
        "verified": True,
        "attempts_remaining": attempts_remaining,
    }


# ── Helpers ─────────────────────────────────────────────────────

def _mask_email(email: str) -> str:
    """Mask email for display: a***@example.com."""
    if "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) <= 1:
        return f"***@{domain}"
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"
