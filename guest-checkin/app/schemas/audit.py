"""Pydantic schemas for audit trail endpoints."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AuditTrailEntry(BaseModel):
    """A single state-transition entry in the audit trail."""

    id: str
    session_id: str
    action: str  # "advance", "decline", "resume", etc.
    from_state: str | None = None
    to_state: str | None = None
    details: dict[str, Any] | None = None
    timestamp: datetime
    actor: str  # "guest", "agent", or "system"

    model_config = {"from_attributes": True}


class AuditTrailResponse(BaseModel):
    """Paginated response for audit trail entries."""

    entries: list[AuditTrailEntry]
    total: int
    page: int
    page_size: int
