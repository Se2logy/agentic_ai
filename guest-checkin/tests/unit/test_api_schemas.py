"""Unit tests for Pydantic schemas — validation and serialization."""

import pytest
from decimal import Decimal
from pydantic import ValidationError

from app.schemas.session import CreateSessionRequest, SessionResponse, SessionStateResponse
from app.schemas.message import SendMessageRequest, MessageResponse, AgentResponse
from app.schemas.guest import GuestInfoUpdate
from app.schemas.reservation import ReservationResponse
from app.schemas.agreement import AgreementRecord
from app.schemas.otp import OTPVerifyRequest, OTPVerifyResponse
from app.schemas.incidental import IncidentalSelectRequest, IncidentalSelectResponse
from app.schemas.state import StateInfo


class TestCreateSessionRequest:
    def test_valid_booking_reference(self):
        req = CreateSessionRequest(booking_reference="BK-2024-001")
        assert req.booking_reference == "BK-2024-001"

    def test_empty_booking_reference_raises(self):
        with pytest.raises(ValidationError):
            CreateSessionRequest(booking_reference="")

    def test_missing_booking_reference_raises(self):
        with pytest.raises(ValidationError):
            CreateSessionRequest()


class TestSendMessageRequest:
    def test_valid_content(self):
        req = SendMessageRequest(content="I agree to the privacy policy")
        assert req.content == "I agree to the privacy policy"

    def test_empty_content_raises(self):
        with pytest.raises(ValidationError):
            SendMessageRequest(content="")

    def test_too_long_content_raises(self):
        with pytest.raises(ValidationError):
            SendMessageRequest(content="x" * 5001)


class TestGuestInfoUpdate:
    def test_all_fields_optional(self):
        update = GuestInfoUpdate()
        assert update.first_name is None
        assert update.last_name is None
        assert update.phone is None

    def test_partial_update(self):
        update = GuestInfoUpdate(first_name="John")
        assert update.first_name == "John"
        assert update.last_name is None


class TestOTPVerifyRequest:
    def test_valid_otp(self):
        req = OTPVerifyRequest(otp_code="123456")
        assert req.otp_code == "123456"

    def test_empty_otp_raises(self):
        with pytest.raises(ValidationError):
            OTPVerifyRequest(otp_code="")


class TestOTPVerifyResponse:
    def test_verified_response(self):
        resp = OTPVerifyResponse(verified=True, attempts_remaining=2, message="OK")
        assert resp.verified is True
        assert resp.attempts_remaining == 2


class TestIncidentalSelectRequest:
    def test_valid_selection(self):
        req = IncidentalSelectRequest(selection_type="damage_waiver")
        assert req.selection_type == "damage_waiver"

    def test_security_hold(self):
        req = IncidentalSelectRequest(selection_type="security_hold")
        assert req.selection_type == "security_hold"

    def test_invalid_selection_type_raises(self):
        with pytest.raises(ValidationError):
            IncidentalSelectRequest(selection_type="bad_option")

    def test_typo_selection_type_raises(self):
        """DATA-004: Literal validation rejects 'damage_waver' (typo of 'damage_waiver')."""
        with pytest.raises(ValidationError):
            IncidentalSelectRequest(selection_type="damage_waver")


class TestIncidentalSelectResponse:
    def test_completed_response(self):
        resp = IncidentalSelectResponse(
            selection_type="damage_waiver",
            amount=Decimal("49.00"),
            payment_status="completed",
            payment_reference="mock-abc123",
            message="Payment processed",
        )
        assert resp.payment_status == "completed"
        assert resp.amount == Decimal("49.00")
        assert isinstance(resp.amount, Decimal)


class TestStateInfo:
    def test_state_info(self):
        info = StateInfo(
            current_state="PRIVACY_POLICY_PENDING",
            required_action="Accept privacy policy",
            progress=14.3,
        )
        assert info.current_state == "PRIVACY_POLICY_PENDING"
        assert info.progress == 14.3


class TestAgreementRecord:
    def test_accepted_record(self):
        rec = AgreementRecord(
            session_id="sess-1",
            agreement_type="privacy_policy",
            accepted=True,
            guest_response="I agree",
        )
        assert rec.accepted is True
        assert rec.agreement_type == "privacy_policy"

    def test_declined_record(self):
        rec = AgreementRecord(
            session_id="sess-1",
            agreement_type="house_rules",
            accepted=False,
        )
        assert rec.accepted is False


class TestSessionStateResponse:
    def test_response(self):
        resp = SessionStateResponse(
            session_id="s-1",
            current_state="INIT",
            required_action="Initialize check-in session",
            status="active",
        )
        assert resp.current_state == "INIT"


class TestAgentResponse:
    def test_response(self):
        msg = MessageResponse(
            id="m-1",
            session_id="s-1",
            role="agent",
            content="Welcome!",
        )
        resp = AgentResponse(
            message=msg,
            current_state="INIT",
            required_action="Initialize check-in session",
            session_status="active",
        )
        assert resp.message.role == "agent"
        assert resp.current_state == "INIT"
