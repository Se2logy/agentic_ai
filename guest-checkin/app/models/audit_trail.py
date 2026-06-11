"""Audit Trail ORM model."""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class AuditTrail(Base):
    """Immutable log of every state transition and significant action."""

    __tablename__ = "audit_trail"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    action = Column(String(100), nullable=False)
    from_state = Column(String(50), nullable=True)
    to_state = Column(String(50), nullable=True)
    details = Column(JSON, nullable=True)
    actor = Column(String(20), nullable=False)  # guest / agent / system
    created_at = Column(DateTime, default=func.now())

    # relationships
    session = relationship("Session", back_populates="audit_entries")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditTrail {self.action} {self.from_state}->{self.to_state}>"
