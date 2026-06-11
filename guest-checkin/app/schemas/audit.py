"""Pydantic schemas for audit trail endpoints."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AuditTrailEntry(BaseModel):
    """A single state-transition entry in the audit trail."""

    from_state: str
    to_state: str
    timestamp: datetime
    actor: str  # "guest" or "system"

    model_config = {"from_attributes": True}


class AuditTrailResponse(BaseModel):
    """Paginated response for audit trail entries."""

    entries: list[AuditTrailEntry]
    total: int
    page: int
    page_size: int
