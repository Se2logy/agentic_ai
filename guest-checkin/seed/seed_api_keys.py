"""Seed API keys — two test keys for local development.

API keys are stored as SHA-256 hashes. The plaintext keys are:
  - test-key-1 (Development Key 1)
  - test-key-2 (Development Key 2)

When using the API, pass the plaintext key in the X-API-Key header.
The system hashes it and compares against the stored hash.
"""

import asyncio
import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.api_key import APIKey


def _hash_key(key: str) -> str:
    """Hash an API key with SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


# Plaintext keys for reference (used in X-API-Key header)
PLAINTEXT_KEYS = {
    "test-key-1": "Development Key 1",
    "test-key-2": "Development Key 2",
}

# Store hashes in the database
API_KEYS = [
    {
        "key": _hash_key(plaintext),
        "name": name,
        "is_active": True,
    }
    for plaintext, name in PLAINTEXT_KEYS.items()
]


async def seed(session: AsyncSession | None = None) -> list[APIKey]:
    """Insert sample API keys (hashed). Uses provided session or creates one."""
    close = False
    if session is None:
        session = async_session_factory()
        close = True

    try:
        for data in API_KEYS:
            api_key = APIKey(**data)
            session.add(api_key)
        await session.commit()
        result = await session.execute(
            select(APIKey).where(
                APIKey.key.in_([d["key"] for d in API_KEYS])
            )
        )
        return list(result.scalars().all())
    finally:
        if close:
            await session.close()


if __name__ == "__main__":
    asyncio.run(seed())
