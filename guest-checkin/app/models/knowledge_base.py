"""Knowledge Base ORM model."""

import uuid

from sqlalchemy import Column, DateTime, String, Text, func

from app.database import Base


class KnowledgeBase(Base):
    """FAQ / property knowledge entries for agent question-answering."""

    __tablename__ = "knowledge_base"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    property_id = Column(String(50), index=True, nullable=False)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:  # pragma: no cover
        return f"<KnowledgeBase q={self.question[:40]!r}>"
