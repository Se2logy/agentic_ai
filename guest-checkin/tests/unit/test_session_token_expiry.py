"""Unit tests for session token absolute expiry (SEC-SESS-001).

Verifies that session tokens expire after exactly 24 hours (SESSION_TOKEN_EXPIRY_HOURS),
not 48h (no *2 multiplication bug — fix F3 from the spec).

Coverage matrix rows:
  - ST-SEC-001: Active → Expired (absolute) when created_at > 24h ago
  - ST-SEC-003: Active → Active (within absolute window) when created_at ≤ 24h ago
  - EC-SEC-003: Stolen token replayed after 25h → rejected
  - EC-SEC-005: Boundary: session created exactly 24h ago → accepted (not yet expired)
  - CSR-SEC-001: Expired absolute → cannot recover (must start new session)
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth.session_token import generate_session_token, verify_session_token
from app.config import settings
from app.database import Base
from app.models import (  # noqa: F401 — needed so Alembic can discover all models
    Agreement,
    APIKey,
    AuditTrail,
    Guest,
    IncidentalSelection,
    KnowledgeBase,
    Message,
    OTPVerification,
    Reservation,
    Session,
)

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ── Fixtures ──────────────────────────────────────────────────────────────────


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


async def _seed_session(db_session: AsyncSession, created_at: datetime) -> Session:
    """Insert a guest, reservation, and session with a specific created_at."""
    g = Guest(
        id=str(uuid.uuid4()),
        email="expiry-test@example.com",
        first_name="Test",
        last_name="User",
        phone="+1-555-0001",
    )
    db_session.add(g)
    await db_session.flush()

    r = Reservation(
        id=str(uuid.uuid4()),
        booking_reference="BK-EXPIRY-TEST",
        property_name="Test Property",
        property_address="1 Test St",
        guest_name="Test User",
        guest_email="expiry-test@example.com",
        guest_phone="+1-555-0001",
        check_in_date=date(2024, 7, 1),
        check_out_date=date(2024, 7, 7),
        num_guests=1,
        wifi_network="TestWiFi",
        wifi_password="test2024",
        lockbox_code="0000",
        emergency_contact="+1-555-0911",
        house_rules_text="No rules.",
        rental_agreement_text="Std.",
        privacy_policy_text="We respect your privacy.",
    )
    db_session.add(r)
    await db_session.flush()

    token = generate_session_token()
    s = Session(
        id=str(uuid.uuid4()),
        reservation_id=r.id,
        guest_id=g.id,
        current_state="INFO_VERIFY_PENDING",
        session_token=token,
        status="active",
        last_message_at=datetime.now(timezone.utc),  # recent activity
        created_at=created_at,
    )
    db_session.add(s)
    await db_session.flush()

    return s


# ── Source code inspection: no *2 bug ─────────────────────────────────────────


class TestNoDoublingBugInSource:
    """Static analysis: confirm the *2 multiplication does not exist."""

    def test_no_multiplication_by_two_in_expiry(self):
        """The absolute expiry line must use token_max_age_hours directly, not * 2.

        This is a source-level guard: if someone re-introduces the bug, this test fails.
        """
        import inspect
        from app.auth import session_token as mod

        source = inspect.getsource(mod.verify_session_token)
        # The original bug was: timedelta(hours=token_max_age_hours * 2)
        # The fix uses: timedelta(hours=token_max_age_hours)
        # Check that "* 2" or "*2" does NOT appear on the absolute expiry line
        for line in source.splitlines():
            if "timedelta" in line and "token_max_age_hours" in line:
                assert "* 2" not in line and "*2" not in line, (
                    f"Bug F3 re-introduced! Found *2 in absolute expiry line: {line.strip()}"
                )

    def test_config_session_token_expiry_is_24(self):
        """Default SESSION_TOKEN_EXPIRY_HOURS must be 24."""
        assert settings.SESSION_TOKEN_EXPIRY_HOURS == 24


# ── Functional tests: absolute expiry boundary ────────────────────────────────


class TestAbsoluteExpiryFunctional:
    """Functional tests using a real DB with manipulated created_at timestamps."""

    @pytest.mark.asyncio
    async def test_session_25h_old_is_rejected(self, db_session):
        """ST-SEC-001 / EC-SEC-003: Session created 25h ago must be rejected.

        A stolen token replayed after 25h should be expired.
        """
        created_25h_ago = datetime.now(timezone.utc) - timedelta(hours=25)
        session = await _seed_session(db_session, created_25h_ago)

        result = await verify_session_token(session.session_token, db_session)
        assert result is None, (
            "Session created 25h ago should be expired (absolute 24h cap), "
            "but verify_session_token returned a session."
        )

    @pytest.mark.asyncio
    async def test_session_23h_old_is_accepted(self, db_session):
        """ST-SEC-003: Session created 23h ago must still be accepted."""
        created_23h_ago = datetime.now(timezone.utc) - timedelta(hours=23)
        session = await _seed_session(db_session, created_23h_ago)

        result = await verify_session_token(session.session_token, db_session)
        assert result is not None, (
            "Session created 23h ago should still be valid (within 24h window), "
            "but verify_session_token returned None."
        )

    @pytest.mark.asyncio
    async def test_session_just_under_24h_is_accepted(self, db_session):
        """EC-SEC-005: Session created just under 24h ago should be accepted.

        The code uses '>' (strictly greater than) for the comparison:
          if now - created_at > timedelta(hours=24)
        We use 23h59m59s ago (1 second before the boundary) to avoid timing
        flakiness while still confirming the boundary is at 24h, not 48h.
        """
        created_just_under_24h = datetime.now(timezone.utc) - timedelta(
            hours=23, minutes=59, seconds=59
        )
        session = await _seed_session(db_session, created_just_under_24h)

        result = await verify_session_token(session.session_token, db_session)
        assert result is not None, (
            "Session created just under 24h ago should be accepted. "
            "The code uses '>', so anything < 24h is NOT expired."
        )

    @pytest.mark.asyncio
    async def test_session_just_over_24h_is_rejected(self, db_session):
        """Boundary: Session created just over 24h ago should be rejected.

        Uses 24h + 1s to confirm the boundary is strictly at 24h.
        If the *2 bug were present, this would be accepted (48h boundary).
        """
        created_just_over_24h = datetime.now(timezone.utc) - timedelta(
            hours=24, seconds=1
        )
        session = await _seed_session(db_session, created_just_over_24h)

        result = await verify_session_token(session.session_token, db_session)
        assert result is None, (
            "Session created just over 24h ago should be rejected. "
            "If this fails, the absolute expiry cap may be > 24h."
        )

    @pytest.mark.asyncio
    async def test_session_48h_old_is_rejected(self, db_session):
        """EC-SEC-003 (extended): If the *2 bug were still present, a 48h-old
        session would be at the boundary (24h*2 = 48h). With the fix, 48h is
        well past the 24h cap and must be rejected.
        """
        created_48h_ago = datetime.now(timezone.utc) - timedelta(hours=48)
        session = await _seed_session(db_session, created_48h_ago)

        result = await verify_session_token(session.session_token, db_session)
        assert result is None, (
            "Session created 48h ago must be rejected. If this passes, the *2 "
            "bug (F3) may have been re-introduced, giving 48h absolute expiry."
        )

    @pytest.mark.asyncio
    async def test_expired_absolute_cannot_recover(self, db_session):
        """CSR-SEC-001: Once absolutely expired, the same token is always rejected.

        Verifying the token a second time must still return None — no recovery.
        """
        created_25h_ago = datetime.now(timezone.utc) - timedelta(hours=25)
        session = await _seed_session(db_session, created_25h_ago)

        # First verification
        result1 = await verify_session_token(session.session_token, db_session)
        assert result1 is None

        # Second verification — must still be rejected
        result2 = await verify_session_token(session.session_token, db_session)
        assert result2 is None, (
            "Expired session should not recover on re-verification."
        )


# ── Idle expiry (SEC-SESS-002, out of scope but quick sanity) ─────────────────


class TestIdleExpirySanity:
    """Quick sanity: idle expiry also uses token_max_age_hours directly."""

    @pytest.mark.asyncio
    async def test_idle_25h_rejected(self, db_session):
        """EC-SEC-004: Session idle for 25h must be rejected."""
        from unittest.mock import patch

        # Create a session that's recent (within absolute window) but idle
        now = datetime.now(timezone.utc)
        created_recently = now - timedelta(hours=1)
        session = await _seed_session(db_session, created_recently)

        # Override last_message_at to simulate 25h of inactivity
        session.last_message_at = now - timedelta(hours=25)
        db_session.add(session)
        await db_session.flush()

        result = await verify_session_token(session.session_token, db_session)
        assert result is None, (
            "Session idle for 25h should be expired (idle timeout exceeded 24h)."
        )
