"""Unit tests for session deduplication — Bug 4.

Verifies that POST /sessions returns the existing session
(resumed=True) when one already exists for the booking_reference,
and creates a new session when none exists.

Tests:
1. test_create_session_returns_existing_active
2. test_create_session_returns_existing_completed
3. test_create_session_new_when_none_exists
"""

import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base, get_db
from app.main import app
from app.models import (  # noqa: F401
    Agreement, APIKey, AuditTrail, Guest,
    IncidentalSelection, KnowledgeBase, Message,
    OTPVerification, Reservation, Session,
)
from app.state_machine.states import State

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
async def db_engine():
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def seeded(db_session: AsyncSession):
    """Seed a guest, reservation, and API key for testing."""
    # Create an API key record with a known hash
    import hashlib
    raw_key = "test-api-key-for-dedup"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    api_key = APIKey(
        id=str(uuid.uuid4()),
        name="test-dedup-key",
        key=key_hash,
        is_active=True,
    )
    db_session.add(api_key)
    await db_session.flush()

    guest = Guest(
        id=str(uuid.uuid4()),
        email="dedup@example.com",
        first_name="Carol",
        last_name="Dedup",
        phone="+1-555-0303",
    )
    db_session.add(guest)
    await db_session.flush()

    reservation = Reservation(
        id=str(uuid.uuid4()),
        booking_reference="BK-DEDUP-002",
        property_name="Lake House",
        property_address="5 Lakeview Dr",
        guest_name="Carol Dedup",
        guest_email="dedup@example.com",
        guest_phone="+1-555-0303",
        check_in_date=date(2024, 9, 1),
        check_out_date=date(2024, 9, 7),
        num_guests=2,
        wifi_network="LakeNet",
        wifi_password="lake2024",
        lockbox_code="5567",
        emergency_contact="+1-555-0911",
        house_rules_text="Quiet hours 10pm-8am.",
        rental_agreement_text="Standard terms.",
        privacy_policy_text="Privacy policy text.",
    )
    db_session.add(reservation)
    await db_session.flush()

    # Commit so data is visible across sessions
    await db_session.commit()

    return {
        "db": db_session,
        "api_key": raw_key,
        "reservation_id": reservation.id,
        "guest_id": guest.id,
        "booking_reference": "BK-DEDUP-002",
    }


def _make_app(db_engine):
    """Create a test app with an overridden DB dependency."""
    factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_get_db():
        async with factory() as session:
            yield session
            await session.commit()

    from app.main import create_app

    test_app = create_app()
    test_app.dependency_overrides[get_db] = _override_get_db
    return test_app


# ── Tests ─────────────────────────────────────────────────────────


class TestSessionDeduplication:
    """Bug 4: session dedup on POST /sessions."""

    @pytest.mark.asyncio
    async def test_create_session_new_when_none_exists(
        self, db_engine, seeded
    ):
        """Calling create_session when no session exists for the booking
        should return a new session with resumed=False (or absent)."""
        test_app = _make_app(db_engine)
        api_key = seeded["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            resp = await client.post(
                "/api/v1/sessions",
                json={
                    "booking_reference": seeded["booking_reference"]
                },
                headers={"X-API-Key": api_key},
            )

        assert resp.status_code == 201
        data = resp.json()

        # New session — resumed should be False or absent (default False)
        assert data.get("resumed", False) is False
        assert data["current_state"] == "INIT"
        assert "id" in data
        assert "session_token" in data

    @pytest.mark.asyncio
    async def test_create_session_returns_existing_active(
        self, db_engine, seeded
    ):
        """Creating a session twice with the same booking_reference
        should return the existing session with resumed=True
        when the first session is still active."""
        test_app = _make_app(db_engine)
        api_key = seeded["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            # First call — creates a new session
            resp1 = await client.post(
                "/api/v1/sessions",
                json={
                    "booking_reference": seeded["booking_reference"]
                },
                headers={"X-API-Key": api_key},
            )
            assert resp1.status_code == 201
            data1 = resp1.json()
            session_id_1 = data1["id"]

            # Second call — same booking_reference → should resume
            resp2 = await client.post(
                "/api/v1/sessions",
                json={
                    "booking_reference": seeded["booking_reference"]
                },
                headers={"X-API-Key": api_key},
            )
            assert resp2.status_code == 201
            data2 = resp2.json()

        # Should return the same session ID
        assert data2["id"] == session_id_1
        # Should indicate resumed
        assert data2["resumed"] is True
        # existing_status should be "active" (not COMPLETED yet)
        assert data2["existing_status"] == "active"

    @pytest.mark.asyncio
    async def test_create_session_returns_existing_completed(
        self, db_engine, seeded
    ):
        """When an existing session is COMPLETED, creating a session
        with the same booking_reference should return it with
        resumed=True and existing_status='completed'."""
        test_app = _make_app(db_engine)
        api_key = seeded["api_key"]

        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            # First call — creates a new session
            resp1 = await client.post(
                "/api/v1/sessions",
                json={
                    "booking_reference": seeded["booking_reference"]
                },
                headers={"X-API-Key": api_key},
            )
            assert resp1.status_code == 201
            data1 = resp1.json()
            session_id_1 = data1["id"]

        # Manually set the session state to COMPLETED
        factory = async_sessionmaker(
            db_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as sess:
            result = await sess.execute(
                select(Session).where(Session.id == session_id_1)
            )
            session_obj = result.scalar_one()
            session_obj.current_state = State.COMPLETED.value
            await sess.commit()

        # Second call — session is now COMPLETED
        async with AsyncClient(
            transport=ASGITransport(app=test_app),
            base_url="http://test",
        ) as client:
            resp2 = await client.post(
                "/api/v1/sessions",
                json={
                    "booking_reference": seeded["booking_reference"]
                },
                headers={"X-API-Key": api_key},
            )
            assert resp2.status_code == 201
            data2 = resp2.json()

        # Should return the same session
        assert data2["id"] == session_id_1
        assert data2["resumed"] is True
        assert data2["existing_status"] == "completed"
