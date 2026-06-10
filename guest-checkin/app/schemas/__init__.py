"""Pydantic request/response schemas for the REST API."""

from app.schemas.agreement import AgreementRecord
from app.schemas.guest import GuestInfoUpdate
from app.schemas.incidental import IncidentalSelectRequest, IncidentalSelectResponse
from app.schemas.message import AgentResponse, MessageResponse, SendMessageRequest
from app.schemas.otp import OTPVerifyRequest, OTPVerifyResponse
from app.schemas.reservation import ReservationResponse
from app.schemas.session import CreateSessionRequest, SessionResponse, SessionStateResponse
from app.schemas.state import StateInfo

__all__ = [
    "CreateSessionRequest",
    "SessionResponse",
    "SessionStateResponse",
    "SendMessageRequest",
    "MessageResponse",
    "AgentResponse",
    "GuestInfoUpdate",
    "ReservationResponse",
    "AgreementRecord",
    "OTPVerifyRequest",
    "OTPVerifyResponse",
    "IncidentalSelectRequest",
    "IncidentalSelectResponse",
    "StateInfo",
]
