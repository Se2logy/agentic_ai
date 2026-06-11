"""Message ORM model."""

import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import relationship

from app.database import Base


class Message(Base):
    """A single message in a check-in conversation."""

    __tablename__ = "messages"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(
        String(36), ForeignKey("sessions.id"), nullable=False, index=True
    )
    role = Column(String(20), nullable=False)  # guest / agent / system
    content = Column(Text, nullable=False)
    intent_detected = Column(String(50), nullable=True)
    tools_called = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=func.now())

    # relationships
    session = relationship("Session", back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Message {self.role} session={self.session_id}>"
