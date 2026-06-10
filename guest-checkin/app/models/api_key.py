"""API Key ORM model."""

import uuid

from sqlalchemy import Boolean, Column, DateTime, String, func

from app.database import Base


class APIKey(Base):
    """API key for authenticating platform integrations."""

    __tablename__ = "api_keys"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<APIKey {self.name}>"
