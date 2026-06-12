"""Pydantic schemas for message endpoints."""

from datetime import datetime

from pydantic import BaseModel, Field


class SendMessageRequest(BaseModel):
    """Guest sends a message to the agent."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The guest's message to the agent",
    )


class MessageResponse(BaseModel):
    """A single message in the conversation."""

    id: str
    session_id: str
    role: str
    content: str
    intent_detected: str | None = None
    tools_called: list | None = None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class AgentResponse(BaseModel):
    """The agent's response after processing a guest message."""

    message: MessageResponse
    current_state: str
    required_action: str
    session_status: str
    instructions_html: str | None = None
