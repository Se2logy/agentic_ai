"""WebSocket endpoint for real-time chat with the check-in agent.

Provides bidirectional communication between the guest client and the
agent, using session tokens for authentication and the SessionManager
for intent detection + state machine processing.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.session_token import verify_session_token
from app.database import async_session_factory
from app.models.session import Session
from app.api.sessions import _session_manager
from app.state_machine.states import State
from app.state_machine.transitions import get_required_action

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


# ── Pydantic schemas for WS messages ───────────────────────────────


class WSIncoming(BaseModel):
    """Schema for messages received from the guest client."""

    content: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The guest's message to the agent",
    )


class WSOutgoing(BaseModel):
    """Schema for messages sent from the server to the guest client."""

    type: str = Field(
        description="Message type: welcome, agent, error, state_update"
    )
    data: dict[str, Any] = Field(
        description="Payload varies by type"
    )


# ── Connection Manager ─────────────────────────────────────────────


class ConnectionManager:
    """Manages active WebSocket connections keyed by session_id.

    Thread-safe for asyncio (single-threaded event loop). If the app
    ever runs across multiple processes, replace with Redis-backed
    pub/sub.
    """

    def __init__(self) -> None:
        self.active_connections: dict[str, WebSocket] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept a WebSocket and register it under session_id.

        If a connection already exists for the session, close the old
        one first (single-connection-per-session policy).
        """
        if session_id in self.active_connections:
            old_ws = self.active_connections[session_id]
            try:
                await old_ws.close(code=status.WS_1008_POLICY_VIOLATION)
            except Exception:
                pass
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info("WebSocket connected: session=%s", session_id)

    async def disconnect(self, session_id: str) -> None:
        """Remove a session from the active connections registry."""
        ws = self.active_connections.pop(session_id, None)
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
            logger.info("WebSocket disconnected: session=%s", session_id)

    async def send_message(self, session_id: str, message: str) -> bool:
        """Send a text message to a specific session.

        Returns True if sent successfully, False if the session is
        not connected.
        """
        ws = self.active_connections.get(session_id)
        if ws is None:
            return False
        try:
            await ws.send_text(message)
            return True
        except Exception:
            logger.warning(
                "Failed to send WS message to session=%s", session_id
            )
            return False

    async def broadcast(
        self, session_ids: list[str], message: str
    ) -> dict[str, bool]:
        """Send a text message to multiple sessions.

        Returns a dict mapping session_id → success (bool).
        """
        results: dict[str, bool] = {}
        for sid in session_ids:
            results[sid] = await self.send_message(sid, message)
        return results

    async def send_state_update(self, session_id: str, data: dict) -> None:
        """Push a state_update message to the WebSocket connection for a session.

        Used by REST endpoints (id_upload, incidental) to notify the chat
        widget when the state machine advances externally.
        """
        ws = self.active_connections.get(session_id)
        if ws is None:
            return
        message = json.dumps({"type": "state_update", **data})
        try:
            await ws.send_text(message)
        except Exception:
            logger.warning(
                "Failed to push state_update to session=%s", session_id
            )

    def is_connected(self, session_id: str) -> bool:
        """Check whether a session currently has an active WS."""
        return session_id in self.active_connections

    async def send_state_update(self, session_id: str, data: dict) -> None:
        """Push a state_update message to the WebSocket connection for a session."""
        ws = self.active_connections.get(session_id)
        if ws is None:
            return
        message = json.dumps({"type": "state_update", **data})
        try:
            await ws.send_text(message)
        except Exception:
            pass


# Singleton instance
manager = ConnectionManager()


# ── WebSocket Rate Limiting ────────────────────────────────────────

# Simple in-memory rate limiter for WebSocket messages
# Limits each session to 30 messages per 60-second window
_ws_rate_limits: dict[str, list[float]] = defaultdict(list)
_WS_RATE_LIMIT_MESSAGES = 30
_WS_RATE_LIMIT_WINDOW = 60  # seconds


def _check_ws_rate_limit(session_id: str) -> bool:
    """Check if a session is within the rate limit. Returns True if allowed."""
    now = time.monotonic()
    timestamps = _ws_rate_limits[session_id]
    # Remove timestamps outside the window
    _ws_rate_limits[session_id] = [
        t for t in timestamps if now - t < _WS_RATE_LIMIT_WINDOW
    ]
    if len(_ws_rate_limits[session_id]) >= _WS_RATE_LIMIT_MESSAGES:
        return False
    _ws_rate_limits[session_id].append(now)
    return True


# ── Message Processing ─────────────────────────────────────────────


async def _process_guest_message(
    session: Session,
    guest_content: str,
    db: AsyncSession,
) -> dict[str, Any]:
    """Process a guest message through the SessionManager.

    Returns a dict suitable for wrapping in a WSOutgoing envelope.
    """
    result = await _session_manager.process_message(
        session_id=session.id,
        guest_message=guest_content,
        db=db,
    )

    # Commit the transaction (SessionManager only flushes)
    await db.commit()

    # Enrich response for specific states
    current_state = State(result["current_state"])

    if current_state == State.COMPLETED:
        instructions = await _session_manager.get_arrival_instructions(
            session.id, db
        )
        if instructions:
            result["agent_content"] += f"\n\n{instructions}"

    elif current_state == State.ID_VERIFY_PENDING:
        upload_url = await _session_manager.get_id_upload_link(
            session.id, db
        )
        if upload_url:
            result["agent_content"] += (
                f"\n\nSecure upload link: {upload_url}"
            )

    elif current_state == State.INCIDENTAL_PROTECTION_PENDING:
        selection_url = await _session_manager.get_incidental_link(
            session.id, db
        )
        if selection_url:
            result["agent_content"] += (
                f"\n\nSelection link: {selection_url}"
            )

    return {
        "message": {
            "session_id": session.id,
            "role": "agent",
            "content": result["agent_content"],
            "intent_detected": result.get("intent_detected"),
            "tools_called": result.get("tools_called"),
        },
        "current_state": result["current_state"],
        "required_action": result.get("required_action", ""),
        "session_status": result.get("session_status", "active"),
    }


# ── WebSocket Endpoint ─────────────────────────────────────────────


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(..., description="Session token for authentication"),
) -> None:
    """WebSocket endpoint for real-time check-in chat.

    Accepts connections at /api/v1/ws/{session_id}?token={session_token}.

    On connect:
        - Validates the session token against the DB
        - Sends a welcome message with current state + required action
        - Registers the connection in the ConnectionManager

    On message:
        - Parses the guest message
        - Processes through the SessionManager (LLM + state machine)
        - Sends the agent response back via WebSocket

    On disconnect:
        - Removes the connection from the ConnectionManager
        - Logs an audit trail entry
    """
    # ── Authenticate ────────────────────────────────────────────────
    async with async_session_factory() as db:
        auth_session = await verify_session_token(token, db)

    if auth_session is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning(
            "WebSocket auth failed: session_id=%s (invalid token)",
            session_id,
        )
        return

    if auth_session.id != session_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning(
            "WebSocket auth failed: token session=%s != path session=%s",
            auth_session.id,
            session_id,
        )
        return

    # ── Connect ─────────────────────────────────────────────────────
    await manager.connect(session_id, websocket)

    try:
        # Send welcome message with current state
        # Re-load session in a fresh DB context (auth_session is detached)
        async with async_session_factory() as db:
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session is None:
                await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
                return
            current_state_val = session.current_state
            try:
                required_action = get_required_action(
                    State(current_state_val)
                )
            except ValueError:
                required_action = "Unknown state"
            session_status = session.status

        welcome_data = {
            "session_id": session_id,
            "current_state": current_state_val,
            "required_action": required_action,
            "session_status": session_status,
        }
        await websocket.send_text(
            WSOutgoing(type="welcome", data=welcome_data).model_dump_json()
        )

        # ── Message loop ────────────────────────────────────────────
        while True:
            raw = await websocket.receive_text()

            # Parse and validate incoming message
            try:
                incoming = WSIncoming.model_validate_json(raw)
            except ValidationError as exc:
                error_msg = WSOutgoing(
                    type="error",
                    data={"detail": "Invalid message format", "errors": str(exc)},
                )
                await websocket.send_text(error_msg.model_dump_json())
                continue

            # Process through SessionManager + state machine
            try:
                # Rate limit check
                if not _check_ws_rate_limit(session_id):
                    error_msg = WSOutgoing(
                        type="error",
                        data={
                            "detail": (
                                f"Rate limit exceeded. Maximum "
                                f"{_WS_RATE_LIMIT_MESSAGES} messages per "
                                f"{_WS_RATE_LIMIT_WINDOW} seconds."
                            ),
                            "error_type": "rate_limit_exceeded",
                        },
                    )
                    await websocket.send_text(error_msg.model_dump_json())
                    continue

                async with async_session_factory() as db:
                    # Re-load session in this DB session
                    result = await db.execute(
                        select(Session).where(Session.id == session_id)
                    )
                    fresh_session = result.scalar_one_or_none()

                    if fresh_session is None or fresh_session.status != "active":
                        error_msg = WSOutgoing(
                            type="error",
                            data={"detail": "Session is no longer active"},
                        )
                        await websocket.send_text(
                            error_msg.model_dump_json()
                        )
                        continue

                    response_data = await _process_guest_message(
                        fresh_session, incoming.content, db
                    )

                # Send agent response
                agent_msg = WSOutgoing(
                    type="agent",
                    data=response_data,
                )
                await websocket.send_text(agent_msg.model_dump_json())

            except Exception as exc:
                logger.exception(
                    "Error processing WS message for session=%s",
                    session_id,
                )
                error_msg = WSOutgoing(
                    type="error",
                    data={"detail": "Internal error processing message"},
                )
                try:
                    await websocket.send_text(error_msg.model_dump_json())
                except Exception:
                    pass

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: session=%s", session_id)

    except Exception as exc:
        logger.exception(
            "Unexpected WebSocket error for session=%s: %s",
            session_id,
            exc,
        )

    finally:
        # ── Disconnect cleanup ──────────────────────────────────────
        await manager.disconnect(session_id)

        # Log audit trail for disconnect
        try:
            async with async_session_factory() as db:
                from app.state_machine.audit import log_audit

                await log_audit(
                    db_session=db,
                    session_id=session_id,
                    action="websocket_disconnect",
                    from_state=None,
                    to_state=None,
                    details={"reason": "client_disconnected"},
                    actor="system",
                )
                await db.commit()
        except Exception:
            logger.warning(
                "Failed to log disconnect audit for session=%s",
                session_id,
            )
