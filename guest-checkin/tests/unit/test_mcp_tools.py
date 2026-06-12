"""Unit tests for MCP tools — registry + all 12 tool implementations."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def db_session():
    """Create an in-memory SQLite session with all tables."""
    from app.database import Base
    from app.models import (  # noqa: F401
        Agreement, APIKey, AuditTrail, Guest,
        IncidentalSelection, KnowledgeBase, Message,
        OTPVerification, Reservation, Session,
    )

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
    """Seed guest, reservation, session, KB. Returns dict with keys."""
    from app.models.guest import Guest
    from app.models.reservation import Reservation
    from app.models.session import Session as Sess
    from app.models.knowledge_base import KnowledgeBase

    g = Guest(
        id=str(uuid.uuid4()), email="test@example.com",
        first_name="Alice", last_name="Johnson", phone="+1-555-0101",
    )
    db_session.add(g)
    await db_session.flush()

    r = Reservation(
        id=str(uuid.uuid4()), booking_reference="BK-TEST-001",
        property_name="Seaside Cottage",
        property_address="12 Ocean Drive, Marina Bay, CA 90210",
        guest_name="Alice Johnson", guest_email="test@example.com",
        guest_phone="+1-555-0101",
        check_in_date=date(2024, 7, 1), check_out_date=date(2024, 7, 7),
        num_guests=2, wifi_network="SeasideWiFi", wifi_password="ocean2024",
        lockbox_code="4482", emergency_contact="+1-555-0911",
        house_rules_text="No smoking.", rental_agreement_text="Std agreement.",
        privacy_policy_text="We respect your privacy.",
    )
    db_session.add(r)
    await db_session.flush()

    s = Sess(
        id=str(uuid.uuid4()), reservation_id=r.id, guest_id=g.id,
        current_state="INFO_VERIFY_PENDING", session_token="tok-123",
        status="active",
    )
    db_session.add(s)
    await db_session.flush()

    kb = KnowledgeBase(
        id=str(uuid.uuid4()), property_id="seaside-cottage",
        question="What time is check-in?",
        answer="Check-in is from 3:00 PM onwards.",
        category="check-in",
    )
    db_session.add(kb)
    await db_session.flush()

    return {"db": db_session, "sid": s.id, "gid": g.id, "rid": r.id}


# ── ToolRegistry tests ──────────────────────────────────────────


class TestToolRegistry:
    def test_register_and_get_tool(self):
        from app.mcp_tools.registry import ToolRegistry
        reg = ToolRegistry()
        h = AsyncMock()
        reg.register("t1", "desc", {"type": "object"}, h)
        assert reg.get_tool("t1") is h

    def test_get_nonexistent_returns_none(self):
        from app.mcp_tools.registry import ToolRegistry
        assert ToolRegistry().get_tool("x") is None

    def test_get_tool_descriptions(self):
        from app.mcp_tools.registry import ToolRegistry
        reg = ToolRegistry()
        reg.register("a", "A", {}, AsyncMock())
        reg.register("b", "B", {}, AsyncMock())
        descs = reg.get_tool_descriptions()
        assert len(descs) == 2
        assert {d["name"] for d in descs} == {"a", "b"}

    def test_get_tool_names_sorted(self):
        from app.mcp_tools.registry import ToolRegistry
        reg = ToolRegistry()
        reg.register("beta", "B", {}, AsyncMock())
        reg.register("alpha", "A", {}, AsyncMock())
        assert reg.get_tool_names() == ["alpha", "beta"]

    def test_register_all_12_tools(self):
        from app.mcp_tools.registry import ToolRegistry
        reg = ToolRegistry()
        reg.register_all()
        assert len(reg.get_tool_names()) == 12

    def test_register_all_expected_names(self):
        from app.mcp_tools.registry import ToolRegistry
        reg = ToolRegistry()
        reg.register_all()
        expected = sorted([
            "generate_id_upload_link", "generate_incidental_link",
            "get_arrival_instructions", "get_current_state",
            "get_faq_answer", "get_reservation",
            "record_agreement", "record_id_upload",
            "record_incidental_selection", "trigger_otp",
            "update_guest_info", "verify_otp",
        ])
        assert reg.get_tool_names() == expected


# ── reservation_tools tests ─────────────────────────────────────


class TestGetReservation:
    @pytest.mark.asyncio
    async def test_found(self, sd):
        from app.mcp_tools.reservation_tools import get_reservation
        result = await get_reservation(sd["db"], "BK-TEST-001")
        assert result is not None
        assert result["booking_reference"] == "BK-TEST-001"
        assert result["property_name"] == "Seaside Cottage"

    @pytest.mark.asyncio
    async def test_not_found(self, db_session):
        from app.mcp_tools.reservation_tools import get_reservation
        assert await get_reservation(db_session, "NOPE") is None

    @pytest.mark.asyncio
    async def test_empty_ref(self, db_session):
        from app.mcp_tools.reservation_tools import get_reservation
        result = await get_reservation(db_session, "")
        assert "error" in result


# ── agreement_tools tests ───────────────────────────────────────


class TestRecordAgreement:
    @pytest.mark.asyncio
    async def test_accept(self, sd):
        from app.mcp_tools.agreement_tools import record_agreement
        r = await record_agreement(sd["db"], sd["sid"], "privacy_policy", True, "ok")
        assert r["recorded"] is True
        assert r["accepted"] is True
        assert r["agreement_type"] == "privacy_policy"

    @pytest.mark.asyncio
    async def test_decline(self, sd):
        from app.mcp_tools.agreement_tools import record_agreement
        r = await record_agreement(sd["db"], sd["sid"], "house_rules", False)
        assert r["recorded"] is True
        assert r["accepted"] is False

    @pytest.mark.asyncio
    async def test_invalid_type(self, sd):
        from app.mcp_tools.agreement_tools import record_agreement
        r = await record_agreement(sd["db"], sd["sid"], "bad", True)
        assert "error" in r

    @pytest.mark.asyncio
    async def test_missing_session(self, db_session):
        from app.mcp_tools.agreement_tools import record_agreement
        r = await record_agreement(db_session, "", "privacy_policy", True)
        assert "error" in r


# ── guest_tools tests ───────────────────────────────────────────


class TestUpdateGuestInfo:
    @pytest.mark.asyncio
    async def test_update_first_name(self, sd):
        from app.mcp_tools.guest_tools import update_guest_info
        r = await update_guest_info(sd["db"], sd["sid"], first_name="Bob")
        assert r["updated"] is True
        assert r["first_name"] == "Bob"
        assert "first_name" in r["updated_fields"]

    @pytest.mark.asyncio
    async def test_update_phone(self, sd):
        from app.mcp_tools.guest_tools import update_guest_info
        r = await update_guest_info(sd["db"], sd["sid"], phone="+1-555-9999")
        assert r["updated"] is True
        assert r["phone"] == "+1-555-9999"

    @pytest.mark.asyncio
    async def test_no_fields(self, sd):
        from app.mcp_tools.guest_tools import update_guest_info
        r = await update_guest_info(sd["db"], sd["sid"])
        assert "error" in r

    @pytest.mark.asyncio
    async def test_invalid_session(self, db_session):
        from app.mcp_tools.guest_tools import update_guest_info
        r = await update_guest_info(db_session, "nope", first_name="X")
        assert "error" in r


# ── otp_tools tests ─────────────────────────────────────────────


class TestTriggerOtp:
    @pytest.mark.asyncio
    async def test_success(self, sd):
        from app.mcp_tools.otp_tools import trigger_otp
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=True,
        ):
            r = await trigger_otp(sd["db"], sd["sid"])
        assert r["otp_sent"] is True
        assert r["email"].endswith("@example.com")

    @pytest.mark.asyncio
    async def test_email_failure(self, sd):
        from app.mcp_tools.otp_tools import trigger_otp
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=False,
        ):
            r = await trigger_otp(sd["db"], sd["sid"])
        assert r["otp_sent"] is False

    @pytest.mark.asyncio
    async def test_invalid_session(self, db_session):
        from app.mcp_tools.otp_tools import trigger_otp
        r = await trigger_otp(db_session, "nope")
        assert "error" in r


class TestVerifyOtp:
    @pytest.mark.asyncio
    async def test_correct_code(self, sd):
        from app.mcp_tools.otp_tools import trigger_otp, verify_otp
        from app.models.otp_verification import OTPVerification
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=True,
        ):
            await trigger_otp(sd["db"], sd["sid"])
        stmt = select(OTPVerification).where(
            OTPVerification.session_id == sd["sid"]
        )
        res = await sd["db"].execute(stmt)
        otp = res.scalar_one()
        r = await verify_otp(sd["db"], sd["sid"], otp.otp_code)
        assert r["verified"] is True

    @pytest.mark.asyncio
    async def test_wrong_code(self, sd):
        from app.mcp_tools.otp_tools import trigger_otp, verify_otp
        with patch(
            "app.mcp_tools.otp_tools.email_service.send_otp_email",
            new_callable=AsyncMock, return_value=True,
        ):
            await trigger_otp(sd["db"], sd["sid"])
        r = await verify_otp(sd["db"], sd["sid"], "000000")
        assert r["verified"] is False
        assert r["attempts_remaining"] == 2

    @pytest.mark.asyncio
    async def test_no_pending(self, sd):
        from app.mcp_tools.otp_tools import verify_otp
        r = await verify_otp(sd["db"], sd["sid"], "123456")
        assert r["verified"] is False
        assert "No pending OTP" in r.get("error", "")


# ── id_upload_tools tests ───────────────────────────────────────


class TestGenerateIdUploadLink:
    @pytest.mark.asyncio
    async def test_success(self, sd):
        from app.mcp_tools.id_upload_tools import generate_id_upload_link
        r = await generate_id_upload_link(sd["db"], sd["sid"])
        assert "upload_url" in r
        assert "/api/v1/id-upload/" in r["upload_url"]
        assert "expires_in" in r

    @pytest.mark.asyncio
    async def test_invalid_session(self, db_session):
        from app.mcp_tools.id_upload_tools import generate_id_upload_link
        r = await generate_id_upload_link(db_session, "nope")
        assert "error" in r


class TestRecordIdUpload:
    @pytest.mark.asyncio
    async def test_success(self, sd):
        from app.mcp_tools.id_upload_tools import record_id_upload
        r = await record_id_upload(sd["db"], sd["sid"], "/uploads/ids/photo.jpg")
        assert r["uploaded"] is True
        assert r["id_verified"] is True
        assert r["id_document_path"] == "/uploads/ids/photo.jpg"

    @pytest.mark.asyncio
    async def test_missing_path(self, sd):
        from app.mcp_tools.id_upload_tools import record_id_upload
        r = await record_id_upload(sd["db"], sd["sid"], "")
        assert "error" in r


# ── incidental_tools tests ──────────────────────────────────────


class TestGenerateIncidentalLink:
    @pytest.mark.asyncio
    async def test_success(self, sd):
        from app.mcp_tools.incidental_tools import generate_incidental_link
        r = await generate_incidental_link(sd["db"], sd["sid"])
        assert "selection_url" in r
        assert "/api/v1/incidental/" in r["selection_url"]
        assert len(r["options"]) == 2
        assert {o["type"] for o in r["options"]} == {"damage_waiver", "security_hold"}


class TestRecordIncidentalSelection:
    @pytest.mark.asyncio
    async def test_damage_waiver(self, sd):
        from app.mcp_tools.incidental_tools import record_incidental_selection
        r = await record_incidental_selection(sd["db"], sd["sid"], "damage_waiver")
        assert r["selected"] is True
        assert r["selection_type"] == "damage_waiver"
        assert r["amount"] == Decimal("49.00")
        assert r["payment"]["success"] is True

    @pytest.mark.asyncio
    async def test_security_hold(self, sd):
        from app.mcp_tools.incidental_tools import record_incidental_selection
        r = await record_incidental_selection(sd["db"], sd["sid"], "security_hold")
        assert r["selected"] is True
        assert r["amount"] == Decimal("250.00")

    @pytest.mark.asyncio
    async def test_invalid_type(self, sd):
        from app.mcp_tools.incidental_tools import record_incidental_selection
        r = await record_incidental_selection(sd["db"], sd["sid"], "bad")
        assert "error" in r

    @pytest.mark.asyncio
    async def test_custom_amount(self, sd):
        from app.mcp_tools.incidental_tools import record_incidental_selection
        r = await record_incidental_selection(sd["db"], sd["sid"], "damage_waiver", Decimal("99.00"))
        assert r["amount"] == Decimal("99.00")


# ── arrival_tools tests ─────────────────────────────────────────


class TestGetArrivalInstructions:
    @pytest.mark.asyncio
    async def test_success(self, sd):
        from app.mcp_tools.arrival_tools import get_arrival_instructions
        r = await get_arrival_instructions(sd["db"], sd["sid"])
        assert "instructions_html" in r
        assert "Seaside Cottage" in r["instructions_html"]

    @pytest.mark.asyncio
    async def test_invalid_session(self, db_session):
        from app.mcp_tools.arrival_tools import get_arrival_instructions
        r = await get_arrival_instructions(db_session, "nope")
        assert "error" in r


# ── faq_tools tests ─────────────────────────────────────────────


class TestGetFaqAnswer:
    @pytest.mark.asyncio
    async def test_match(self, sd):
        from app.mcp_tools.faq_tools import get_faq_answer
        r = await get_faq_answer(sd["db"], sd["sid"], "What time is check-in?")
        assert r["answer"] != "I don't have information about that."
        assert r["category"] == "check-in"

    @pytest.mark.asyncio
    async def test_no_match(self, sd):
        from app.mcp_tools.faq_tools import get_faq_answer
        r = await get_faq_answer(sd["db"], sd["sid"], "What is the meaning of life?")
        assert r["answer"] == "I don't have information about that."

    @pytest.mark.asyncio
    async def test_empty_question(self, sd):
        from app.mcp_tools.faq_tools import get_faq_answer
        r = await get_faq_answer(sd["db"], sd["sid"], "")
        assert "error" in r


class TestGetCurrentState:
    @pytest.mark.asyncio
    async def test_success(self, sd):
        from app.mcp_tools.faq_tools import get_current_state
        r = await get_current_state(sd["db"], sd["sid"])
        assert r["state"] == "INFO_VERIFY_PENDING"
        assert "required_action" in r

    @pytest.mark.asyncio
    async def test_invalid_session(self, db_session):
        from app.mcp_tools.faq_tools import get_current_state
        r = await get_current_state(db_session, "nope")
        assert "error" in r
