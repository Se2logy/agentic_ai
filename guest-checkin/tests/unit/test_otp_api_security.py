"""Unit tests for OTP security — SEC-OTP-001 and SEC-OTP-002.

Verifies:
- SEC-OTP-001: OTP verification uses hmac.compare_digest (constant-time), not ==
- SEC-OTP-002: OTP generation uses secrets.randbelow/secrets.choice, not random.choices
"""

import ast
import inspect
import uuid
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app.models import (  # noqa: F401
    Agreement, APIKey, AuditTrail, Guest,
    IncidentalSelection, KnowledgeBase, Message,
    OTPVerification, Reservation, Session,
)

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


# ── Source inspection tests (no DB required) ────────────────────────


class TestOtpSourceInspection:
    """Inspect source code to confirm security properties."""

    def test_otp_tools_imports_secrets_not_random(self):
        """otp_tools.py must import secrets and must NOT import random.choices."""
        from app.mcp_tools import otp_tools

        # Verify `secrets` is in the module's namespace
        assert hasattr(otp_tools, "secrets"), (
            "otp_tools must import the `secrets` module for CSPRNG"
        )

        # Verify the module does NOT use random.choices or random.randint
        source = inspect.getsource(otp_tools)
        assert "random.choices" not in source, (
            "otp_tools must not use random.choices — use secrets.randbelow or secrets.choice instead"
        )
        assert "random.randint" not in source, (
            "otp_tools must not use random.randint — use secrets.randbelow or secrets.choice instead"
        )
        assert "random.random" not in source, (
            "otp_tools must not use random.random — use secrets.randbelow or secrets.choice instead"
        )

    def test_api_otp_imports_otp_tools_not_random(self):
        """app/api/otp.py must delegate to otp_tools and not use random directly."""
        from app.api import otp as otp_api

        source = inspect.getsource(otp_api)
        assert "random.choices" not in source, (
            "api/otp.py must not use random.choices — it should delegate to otp_tools"
        )
        assert "random.randint" not in source, (
            "api/otp.py must not use random.randint"
        )
        # Confirm delegation pattern
        assert "otp_tools.trigger_otp" in source, (
            "api/otp.py should delegate trigger to otp_tools.trigger_otp"
        )
        assert "otp_tools.verify_otp" in source, (
            "api/otp.py should delegate verify to otp_tools.verify_otp"
        )

    def test_trigger_otp_uses_secrets_randbelow(self):
        """trigger_otp function source must reference secrets.randbelow."""
        from app.mcp_tools.otp_tools import trigger_otp

        source = inspect.getsource(trigger_otp)
        assert "secrets.randbelow" in source, (
            "trigger_otp must use secrets.randbelow for OTP digit generation"
        )

    def test_verify_otp_uses_hmac_compare_digest(self):
        """verify_otp function source must reference hmac.compare_digest."""
        from app.mcp_tools.otp_tools import verify_otp

        source = inspect.getsource(verify_otp)
        assert "hmac.compare_digest" in source, (
            "verify_otp must use hmac.compare_digest for constant-time comparison"
        )


# ── Runtime patching tests (confirm secrets.randbelow is actually called) ──


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite session with all tables."""
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
async def sd(db_session: AsyncSession):
    """Seed guest, reservation, session. Returns dict with keys."""
    from app.models.guest import Guest
    from app.models.reservation import Reservation
    from app.models.session import Session as Sess

    g = Guest(
        id=str(uuid.uuid4()), email="test@example.com",
        first_name="Alice", last_name="Johnson", phone="+1-555-0101",
    )
    db_session.add(g)
    await db_session.flush()

    r = Reservation(
        id=str(uuid.uuid4()), booking_reference="BK-SEC-TEST",
        property_name="Seaside Cottage",
        property_address="12 Ocean Drive",
        guest_name="Alice Johnson", guest_email="test@example.com",
        guest_phone="+1-555-0101",
        check_in_date=date(2024, 7, 1), check_out_date=date(2024, 7, 7),
        num_guests=2, wifi_network="SeasideWiFi", wifi_password="ocean2024",
        lockbox_code="4482", emergency_contact="+1-555-0911",
        house_rules_text="No smoking.", rental_agreement_text="Std.",
        privacy_policy_text="We respect your privacy.",
    )
    db_session.add(r)
    await db_session.flush()

    s = Sess(
        id=str(uuid.uuid4()), reservation_id=r.id, guest_id=g.id,
        current_state="INFO_VERIFY_PENDING", session_token="tok-sec-test",
        status="active",
    )
    db_session.add(s)
    await db_session.flush()

    return {"db": db_session, "sid": s.id, "gid": g.id}


class TestOtpRngPatching:
    """SEC-OTP-002: Patch secrets.randbelow to confirm it is the actual RNG source."""

    @pytest.mark.asyncio
    async def test_secrets_randbelow_called_six_times(self, sd):
        """Patching secrets.randbelow should be called exactly 6 times for a 6-digit OTP."""
        from app.mcp_tools.otp_tools import trigger_otp

        call_count = 0

        def fake_randbelow(n):
            nonlocal call_count
            call_count += 1
            return 7  # deterministic digit for testing

        with patch(
            "app.mcp_tools.otp_tools.secrets.randbelow",
            side_effect=fake_randbelow,
        ), patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await trigger_otp(sd["db"], sd["sid"])

        assert result["otp_sent"] is True, f"OTP trigger failed: {result}"
        assert call_count == 6, (
            f"Expected secrets.randbelow to be called 6 times for 6-digit OTP, "
            f"but it was called {call_count} times"
        )

    @pytest.mark.asyncio
    async def test_otp_digits_come_from_secrets(self, sd):
        """OTP code digits must come from secrets.randbelow, producing values 0-9."""
        from app.mcp_tools.otp_tools import trigger_otp

        captured_values = []

        def fake_randbelow(n):
            assert n == 10, f"secrets.randbelow should be called with 10 (digits 0-9), got {n}"
            captured_values.append(5)  # return a valid digit
            return 5

        with patch(
            "app.mcp_tools.otp_tools.secrets.randbelow",
            side_effect=fake_randbelow,
        ), patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await trigger_otp(sd["db"], sd["sid"])

        assert result["otp_sent"] is True
        assert len(captured_values) == 6, "Should generate exactly 6 digits"

    @pytest.mark.asyncio
    async def test_random_choices_not_used_in_otp_generation(self, sd):
        """If random.choices were used instead of secrets.randbelow, this test catches it.

        We patch secrets.randbelow to raise if called, AND patch random.choices
        to detect if it's invoked. secrets.randbelow must be the path taken.
        """
        import random as random_module
        from app.mcp_tools.otp_tools import trigger_otp

        random_choices_called = False
        original_choices = random_module.choices

        def spy_choices(*args, **kwargs):
            nonlocal random_choices_called
            random_choices_called = True
            return original_choices(*args, **kwargs)

        # Patch both: secrets.randbelow works normally, random.choices is spied on
        with patch(
            "app.mcp_tools.otp_tools.secrets.randbelow",
            return_value=3,
        ), patch(
            "random.choices",
            side_effect=spy_choices,
        ), patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await trigger_otp(sd["db"], sd["sid"])

        assert result["otp_sent"] is True
        assert not random_choices_called, (
            "random.choices must NOT be called during OTP generation — "
            "use secrets.randbelow or secrets.choice instead"
        )


class TestOtpCompareDigestPatching:
    """SEC-OTP-001: Patch hmac.compare_digest to confirm it is the actual comparison function."""

    @pytest.mark.asyncio
    async def test_hmac_compare_digest_called_on_verify(self, sd):
        """verify_otp must call hmac.compare_digest, not ==, for OTP comparison."""
        from app.mcp_tools.otp_tools import trigger_otp, verify_otp

        compare_called = False

        def fake_compare(a, b):
            nonlocal compare_called
            compare_called = True
            return a == b  # still return correct result, just spy on the call

        # First trigger an OTP
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock,
            return_value=True,
        ):
            trigger_result = await trigger_otp(sd["db"], sd["sid"])
        assert trigger_result["otp_sent"] is True

        # Read the generated OTP from DB
        from sqlalchemy import select
        stmt = select(OTPVerification).where(
            OTPVerification.session_id == sd["sid"]
        )
        res = await sd["db"].execute(stmt)
        otp_record = res.scalar_one()

        # Now verify with compare_digest spy
        with patch(
            "app.mcp_tools.otp_tools.hmac.compare_digest",
            side_effect=fake_compare,
        ):
            result = await verify_otp(sd["db"], sd["sid"], otp_record.otp_code)

        assert result["verified"] is True
        assert compare_called, (
            "hmac.compare_digest must be called during OTP verification "
            "to prevent timing attacks"
        )
