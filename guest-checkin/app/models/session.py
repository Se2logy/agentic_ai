"""Session ORM model."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class Session(Base):
    """Represents a check-in session for a guest/reservation pair."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reservation_id = Column(
        String(36), ForeignKey("reservations.id"), nullable=False
    )
    guest_id = Column(String(36), ForeignKey("guests.id"), nullable=False)
    current_state = Column(String(50), default="INIT")
    session_token = Column(String(255), unique=True, index=True, nullable=False)
    status = Column(String(20), default="active")
    last_message_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # relationships
    reservation = relationship("Reservation", back_populates="sessions")
    guest = relationship("Guest", back_populates="sessions")
    agreements = relationship("Agreement", back_populates="session")
    otp_verifications = relationship("OTPVerification", back_populates="session")
    incidental_selections = relationship(
        "IncidentalSelection", back_populates="session"
    )
    messages = relationship("Message", back_populates="session")
    audit_entries = relationship("AuditTrail", back_populates="session")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Session {self.id} state={self.current_state}>"
