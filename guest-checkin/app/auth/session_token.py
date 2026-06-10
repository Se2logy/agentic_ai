"""Session token management — generation and validation for guest-facing endpoints."""

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.session import Session


def generate_session_token() -> str:
    """Generate a cryptographically random session token.

    Uses secrets.token_urlsafe(32) for 256-bit entropy.
    """
    return secrets.token_urlsafe(32)


async def verify_session_token(
    token: str,
    db_session: AsyncSession,
) -> Session | None:
    """Validate a session token against the database.

    Returns the Session row if found and active, else None.
    A session is considered expired if last_message_at is older
    than 24 hours (configurable threshold).
    """
    result = await db_session.execute(
        select(Session).where(Session.session_token == token, Session.status == "active")
    )
    session = result.scalar_one_or_none()

    if session is None:
        return None

    # Check token expiry: sessions expire after SESSION_TOKEN_EXPIRY_HOURS from creation
    # (absolute expiry), or after 24h of inactivity (idle timeout), whichever comes first
    from app.config import settings

    token_max_age_hours = settings.SESSION_TOKEN_EXPIRY_HOURS
    now = datetime.now(timezone.utc)

    # Absolute expiry: session created too long ago
    created_at = session.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if now - created_at > timedelta(hours=token_max_age_hours):  # absolute max: 24h from creation
        return None

    # Idle expiry: no activity for SESSION_TOKEN_EXPIRY_HOURS
    if session.last_message_at is not None:
        last_active = session.last_message_at
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)
        if now - last_active > timedelta(hours=token_max_age_hours):
            return None

    return session


async def get_session(
    authorization: str = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> Session:
    """FastAPI dependency that reads Authorization: Bearer <token> and validates it.

    Raises HTTPException(401) if the header is missing, malformed, or the token is invalid/expired.
    """
    if authorization is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required",
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format. Expected: Bearer <token>",
        )

    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty bearer token",
        )

    session = await verify_session_token(token, db)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
        )

    return session
