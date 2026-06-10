"""Agreement ORM model."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class Agreement(Base):
    """Records guest acceptance or refusal of an agreement."""

    __tablename__ = "agreements"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(
        String(36), ForeignKey("sessions.id"), nullable=False
    )
    agreement_type = Column(
        String(50), nullable=False
    )  # privacy_policy / house_rules / rental_agreement
    accepted = Column(Boolean, nullable=False)
    guest_response = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=func.now())

    # relationships
    session = relationship("Session", back_populates="agreements")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Agreement {self.agreement_type} accepted={self.accepted}>"
