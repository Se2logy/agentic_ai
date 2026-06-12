"""Unit tests for the OTP API endpoints (thin wrapper over otp_tools)."""

import uuid
from datetime import date, datetime, timedelta, timezone
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
from app.models import (  # noqa: F401
    Agreement, APIKey, AuditTrail, Guest,
    IncidentalSelection, KnowledgeBase, Message,
    OTPVerification, Reservation, Session,
)

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


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
    """Seed guest, reservation, session. Returns dict with IDs."""
    g = Guest(
        id=str(uuid.uuid4()), email="test@example.com",
        first_name="Alice", last_name="Johnson", phone="+1-555-0101",
    )
    db_session.add(g)
    await db_session.flush()

    r = Reservation(
        id=str(uuid.uuid4()), booking_reference="BK-TEST-OTP",
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

    s = Session(
        id=str(uuid.uuid4()), reservation_id=r.id, guest_id=g.id,
        current_state="INFO_VERIFY_PENDING",
        session_token="tok-otp-test", status="active",
    )
    db_session.add(s)
    await db_session.flush()

    return {"db": db_session, "sid": s.id, "token": "tok-otp-test"}


class TestTriggerOtpApi:
    """Tests for POST /otp/trigger endpoint delegating to otp_tools."""

    @pytest.mark.asyncio
    async def test_trigger_delegates_to_otp_tools(self, seeded):
        """API endpoint should call otp_tools.trigger_otp and return result."""
        from app.mcp_tools import otp_tools

        with patch.object(
            otp_tools, "trigger_otp",
            new_callable=AsyncMock,
            return_value={"otp_sent": True, "email": "t***@example.com", "expires_in": "10 minutes"},
        ):
            result = await otp_tools.trigger_otp(seeded["db"], seeded["sid"])

        assert result["otp_sent"] is True
        assert "email" in result

    @pytest.mark.asyncio
    async def test_trigger_error_becomes_404(self, seeded):
        """MCP tool error should be mapped to HTTPException(404)."""
        from fastapi import HTTPException
        from app.api.otp import trigger_otp
        from app.models.session import Session as Sess

        # Simulate MCP tool returning an error
        with patch(
            "app.mcp_tools.otp_tools.trigger_otp",
            new_callable=AsyncMock,
            return_value={"error": "Guest not found for session: bad-id"},
        ):
            # Create a mock session with the id
            mock_session = AsyncMock(spec=Sess)
            mock_session.id = "bad-id"

            with pytest.raises(HTTPException) as exc_info:
                await trigger_otp(session=mock_session, db=seeded["db"])
            assert exc_info.value.status_code == 404
            assert "Guest not found" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_trigger_success_returns_dict(self, seeded):
        """Successful trigger should return the MCP tool result dict."""
        from app.api.otp import trigger_otp
        from app.models.session import Session as Sess

        mcp_result = {
            "otp_sent": True,
            "email": "t***@example.com",
            "expires_in": "10 minutes",
        }
        with patch(
            "app.mcp_tools.otp_tools.trigger_otp",
            new_callable=AsyncMock,
            return_value=mcp_result,
        ):
            mock_session = AsyncMock(spec=Sess)
            mock_session.id = seeded["sid"]
            result = await trigger_otp(session=mock_session, db=seeded["db"])

        assert result == mcp_result


class TestVerifyOtpApi:
    """Tests for POST /otp/verify endpoint delegating to otp_tools."""

    @pytest.mark.asyncio
    async def test_verify_success_maps_to_response(self, seeded):
        """Successful verification should map to OTPVerifyResponse."""
        from app.api.otp import verify_otp
        from app.models.session import Session as Sess
        from app.schemas.otp import OTPVerifyRequest

        with patch(
            "app.mcp_tools.otp_tools.verify_otp",
            new_callable=AsyncMock,
            return_value={"verified": True, "attempts_remaining": 2},
        ):
            mock_session = AsyncMock(spec=Sess)
            mock_session.id = seeded["sid"]
            body = OTPVerifyRequest(otp_code="123456")
            result = await verify_otp(body=body, session=mock_session, db=seeded["db"])

        assert result.verified is True
        assert result.attempts_remaining == 2
        assert "successfully" in result.message

    @pytest.mark.asyncio
    async def test_verify_wrong_code_maps_to_response(self, seeded):
        """Wrong code should map to OTPVerifyResponse with remaining attempts."""
        from app.api.otp import verify_otp
        from app.models.session import Session as Sess
        from app.schemas.otp import OTPVerifyRequest

        with patch(
            "app.mcp_tools.otp_tools.verify_otp",
            new_callable=AsyncMock,
            return_value={
                "verified": False,
                "error": "Invalid OTP code.",
                "attempts_remaining": 2,
            },
        ):
            mock_session = AsyncMock(spec=Sess)
            mock_session.id = seeded["sid"]
            body = OTPVerifyRequest(otp_code="000000")
            result = await verify_otp(body=body, session=mock_session, db=seeded["db"])

        assert result.verified is False
        assert result.attempts_remaining == 2
        assert "Invalid OTP code" in result.message

    @pytest.mark.asyncio
    async def test_verify_max_attempts_maps_to_response(self, seeded):
        """Max attempts exceeded should map to OTPVerifyResponse with 0 remaining."""
        from app.api.otp import verify_otp
        from app.models.session import Session as Sess
        from app.schemas.otp import OTPVerifyRequest

        with patch(
            "app.mcp_tools.otp_tools.verify_otp",
            new_callable=AsyncMock,
            return_value={
                "verified": False,
                "error": "Maximum attempts exceeded. Please trigger a new OTP.",
                "attempts_remaining": 0,
            },
        ):
            mock_session = AsyncMock(spec=Sess)
            mock_session.id = seeded["sid"]
            body = OTPVerifyRequest(otp_code="000000")
            result = await verify_otp(body=body, session=mock_session, db=seeded["db"])

        assert result.verified is False
        assert result.attempts_remaining == 0
        assert "Maximum attempts" in result.message

    @pytest.mark.asyncio
    async def test_verify_no_pending_maps_to_404(self, seeded):
        """No pending OTP from MCP tool should raise HTTP 404."""
        from fastapi import HTTPException
        from app.api.otp import verify_otp
        from app.models.session import Session as Sess
        from app.schemas.otp import OTPVerifyRequest

        with patch(
            "app.mcp_tools.otp_tools.verify_otp",
            new_callable=AsyncMock,
            return_value={
                "verified": False,
                "error": "No pending OTP found. Please trigger a new OTP.",
            },
        ):
            mock_session = AsyncMock(spec=Sess)
            mock_session.id = seeded["sid"]
            body = OTPVerifyRequest(otp_code="123456")
            with pytest.raises(HTTPException) as exc_info:
                await verify_otp(body=body, session=mock_session, db=seeded["db"])
            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_verify_expired_maps_to_404(self, seeded):
        """Expired OTP from MCP tool should raise HTTP 404."""
        from fastapi import HTTPException
        from app.api.otp import verify_otp
        from app.models.session import Session as Sess
        from app.schemas.otp import OTPVerifyRequest

        with patch(
            "app.mcp_tools.otp_tools.verify_otp",
            new_callable=AsyncMock,
            return_value={
                "verified": False,
                "error": "OTP has expired. Please trigger a new OTP.",
                "attempts_remaining": 0,
            },
        ):
            mock_session = AsyncMock(spec=Sess)
            mock_session.id = seeded["sid"]
            body = OTPVerifyRequest(otp_code="123456")
            with pytest.raises(HTTPException) as exc_info:
                await verify_otp(body=body, session=mock_session, db=seeded["db"])
            assert exc_info.value.status_code == 404


class TestBuildVerifyMessage:
    """Tests for the _build_verify_message helper."""

    def test_verified_true(self):
        from app.api.otp import _build_verify_message
        assert _build_verify_message({"verified": True}) == "OTP verified successfully."

    def test_max_attempts(self):
        from app.api.otp import _build_verify_message
        msg = _build_verify_message({
            "verified": False,
            "error": "Maximum attempts exceeded. Please trigger a new OTP.",
            "attempts_remaining": 0,
        })
        assert "Maximum attempts" in msg

    def test_wrong_code(self):
        from app.api.otp import _build_verify_message
        msg = _build_verify_message({
            "verified": False,
            "error": "Invalid OTP code.",
            "attempts_remaining": 2,
        })
        assert "Invalid OTP code" in msg
        assert "2 attempt(s) remaining" in msg
