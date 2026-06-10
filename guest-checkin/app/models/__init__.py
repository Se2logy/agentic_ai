"""ORM models — import all models here so Alembic and the app can discover them."""

from app.models.agreement import Agreement
from app.models.api_key import APIKey
from app.models.audit_trail import AuditTrail
from app.models.guest import Guest
from app.models.incidental_selection import IncidentalSelection
from app.models.knowledge_base import KnowledgeBase
from app.models.message import Message
from app.models.otp_verification import OTPVerification
from app.models.reservation import Reservation
from app.models.session import Session

__all__ = [
    "Agreement",
    "APIKey",
    "AuditTrail",
    "Guest",
    "IncidentalSelection",
    "KnowledgeBase",
    "Message",
    "OTPVerification",
    "Reservation",
    "Session",
]
