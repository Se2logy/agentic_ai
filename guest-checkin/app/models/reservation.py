"""Reservation ORM model."""

import uuid

from sqlalchemy import Column, Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base


class Reservation(Base):
    """Represents a property reservation / booking."""

    __tablename__ = "reservations"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    booking_reference = Column(String(50), unique=True, index=True, nullable=False)
    property_name = Column(String(255), nullable=False)
    property_address = Column(Text, nullable=False)
    guest_name = Column(String(255), nullable=False)
    guest_email = Column(String(255), nullable=False)
    guest_phone = Column(String(50), nullable=True)
    check_in_date = Column(Date, nullable=False)
    check_out_date = Column(Date, nullable=False)
    num_guests = Column(Integer, default=1)
    wifi_network = Column(String(255), nullable=True)
    wifi_password = Column(String(255), nullable=True)
    lockbox_code = Column(String(50), nullable=True)
    emergency_contact = Column(String(255), nullable=True)
    house_rules_text = Column(Text, nullable=False)
    rental_agreement_text = Column(Text, nullable=False)
    privacy_policy_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    # relationships
    sessions = relationship("Session", back_populates="reservation")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Reservation {self.booking_reference}>"
