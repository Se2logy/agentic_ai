"""SQLAlchemy async engine, session factory, and declarative base."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# The DATABASE_URL uses pymysql (sync driver). For async SQLAlchemy we need
# the async variant. We swap the driver suffix here so the rest of the
# codebase can use the same env var regardless of driver flavour.
_ASYNC_DB_URL = settings.DATABASE_URL.replace(
    "mysql+pymysql://", "mysql+aiomysql://", 1
)

engine = create_async_engine(_ASYNC_DB_URL, pool_pre_ping=True, echo=False)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async database session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
