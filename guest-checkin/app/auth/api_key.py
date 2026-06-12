"""API key validation — FastAPI dependency for platform integrations.

API keys are stored as SHA-256 hashes in the database. The plaintext key
is only shown once when created; subsequent lookups use hash comparison.
"""

import hashlib

from fastapi import Depends, HTTPException, Header, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.api_key import APIKey
from app.models.session import Session


def _hash_api_key(key: str) -> str:
    """Hash an API key with SHA-256 for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


async def verify_api_key(
    api_key: str,
    db_session: AsyncSession,
) -> APIKey | None:
    """Look up an API key in the database by its hash.

    Returns the APIKey row if found and active, else None.
    """
    key_hash = _hash_api_key(api_key)
    result = await db_session.execute(
        select(APIKey).where(APIKey.key == key_hash, APIKey.is_active.is_(True))
    )
    return result.scalar_one_or_none()


async def get_api_key(
    x_api_key: str = Header(None, alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> APIKey:
    """FastAPI dependency that reads the X-API-Key header and validates it.

    Raises HTTPException(401) if the header is missing or the key is invalid.
    """
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-API-Key header is required",
        )

    api_key_obj = await verify_api_key(x_api_key, db)
    if api_key_obj is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive API key",
        )

    return api_key_obj


async def get_api_key_or_session(
    x_api_key: str = Header(None, alias="X-API-Key"),
    authorization: str = Header(None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
) -> APIKey | Session:
    """FastAPI dependency that accepts either X-API-Key or Bearer session token.

    Tries API key first, then session token. Raises 401 if neither works.
    """
    # Try API key first
    if x_api_key is not None:
        api_key_obj = await verify_api_key(x_api_key, db)
        if api_key_obj is not None:
            return api_key_obj

    # Try session token
    if authorization is not None:
        from app.auth.session_token import verify_session_token
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            session = await verify_session_token(token, db)
            if session is not None:
                return session

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="X-API-Key header or Authorization Bearer token is required",
    )
