"""OTP Verification ORM model."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class OTPVerification(Base):
    """One-time password verification record for guest identity."""

    __tablename__ = "otp_verifications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(
        String(36), ForeignKey("sessions.id"), nullable=False
    )
    email = Column(String(255), nullable=False)
    otp_code = Column(String(10), index=True, nullable=False)
    verified = Column(Boolean, default=False)
    attempts = Column(Integer, default=0)
    max_attempts = Column(Integer, default=3)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=func.now())

    # relationships
    session = relationship("Session", back_populates="otp_verifications")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<OTPVerification email={self.email} verified={self.verified}>"
