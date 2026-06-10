"""Guest ORM model."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlalchemy.orm import relationship

from app.database import Base


class Guest(Base):
    """Represents a guest who goes through the check-in flow."""

    __tablename__ = "guests"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = Column(String(255), unique=True, index=True, nullable=False)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=False)
    phone = Column(String(50), nullable=True)
    id_document_path = Column(String(255), nullable=True)
    id_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # relationships
    sessions = relationship("Session", back_populates="guest")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Guest {self.email}>"
