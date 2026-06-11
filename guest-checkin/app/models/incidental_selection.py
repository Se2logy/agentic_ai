"""Incidental Selection ORM model."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class IncidentalSelection(Base):
    """Guest's incidental protection selection and payment record."""

    __tablename__ = "incidental_selections"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(
        String(36), ForeignKey("sessions.id"), nullable=False
    )
    selection_type = Column(
        String(50), nullable=False
    )  # damage_waiver / security_hold
    amount = Column(Numeric(10, 2), nullable=False, default=0.0)  # DECIMAL(10,2) — avoids floating-point precision loss
    payment_status = Column(
        String(20), default="pending"
    )  # pending / completed / failed
    payment_reference = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=func.now())

    # relationships
    session = relationship("Session", back_populates="incidental_selections")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<IncidentalSelection {self.selection_type} {self.payment_status}>"
