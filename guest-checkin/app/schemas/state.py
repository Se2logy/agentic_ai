"""Pydantic schemas for state information."""

from pydantic import BaseModel


class StateInfo(BaseModel):
    """Current state of the check-in workflow."""

    current_state: str
    required_action: str
    progress: float = 0.0
