"""Integration tests for the WebSocket endpoint.

Tests cover:
- Connection with a valid session token
- Rejection with an invalid token
- Sending a message and receiving an agent response
- Disconnect and reconnect behavior
- Invalid message format handling
- Message persistence to DB
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.guest import Guest
from app.models.message import Message
from app.models.reservation import Reservation
from app.models.session import Session
from app.auth.session_token import generate_session_token, verify_session_token
from app.state_machine.states import State

# ── In-memory SQLite for testing ────────────────────────────────────

SQLALCHEMY_DATABASE_URL = (
    "sqlite+aiosqlite:///file::memory:?cache=shared&uri=true"
)

_test_engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

_test_session_factory = async_sessionmaker(
    _test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@event.listens_for(_test_engine.sync_engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


@pytest.fixture(autouse=True)
async def _setup_db(monkeypatch):
    """Create tables, patch the websocket's session factory, then drop."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Patch the websocket module to use the test session factory
    import app.api.websocket as ws_mod
    monkeypatch.setattr(ws_mod, "async_session_factory", _test_session_factory)

    yield

    # Clean up active connections
    ws_mod.manager.active_connections.clear()

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


# ── Helpers ─────────────────────────────────────────────────────────


async def _create_test_session() -> tuple[str, str]:
    """Create a session + token in the test DB and return (session_id, token)."""
    async with _test_session_factory() as db:
        guest = Guest(
            email=f"ws-test-{uuid.uuid4().hex[:8]}@example.com",
            first_name="Test",
            last_name="Guest",
            phone="+1234567890",
        )
        db.add(guest)
        await db.flush()

        reservation = Reservation(
            booking_reference=f"BK-WS-{uuid.uuid4().hex[:8]}",
            guest_name="Test Guest",
            guest_email=guest.email,
            property_name="Test Property",
            property_address="123 Test St",
            check_in_date=date(2025, 7, 1),
            check_out_date=date(2025, 7, 7),
            num_guests=2,
            house_rules_text="No smoking",
            rental_agreement_text="Standard rental terms",
            privacy_policy_text="We respect your privacy",
        )
        db.add(reservation)
        await db.flush()

        token = generate_session_token()
        session = Session(
            reservation_id=reservation.id,
            guest_id=guest.id,
            session_token=token,
            current_state=State.INIT.value,
            status="active",
            last_message_at=datetime.now(timezone.utc),
        )
        db.add(session)
        await db.flush()

        await db.commit()
        return session.id, token


# ── Import app AFTER patching ───────────────────────────────────────

from starlette.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


# ── Tests ───────────────────────────────────────────────────────────


class TestWebSocketConnect:
    """Tests for WebSocket connection lifecycle."""

    def test_connect_with_valid_token(self):
        """WebSocket should accept a connection with a valid session
        token and send a welcome message."""
        import asyncio

        session_id, token = asyncio.get_event_loop().run_until_complete(
            _create_test_session()
        )

        client = TestClient(app)
        with client.websocket_connect(
            f"/api/v1/ws/{session_id}?token={token}"
        ) as ws:
            raw = ws.receive_text()
            data = json.loads(raw)
            assert data["type"] == "welcome"
            assert data["data"]["session_id"] == session_id
            assert data["data"]["current_state"] == "INIT"
            assert "required_action" in data["data"]

    def test_connect_with_invalid_token(self):
        """WebSocket should close the connection when the token is
        invalid (expired or nonexistent)."""
        import asyncio

        session_id, token = asyncio.get_event_loop().run_until_complete(
            _create_test_session()
        )

        # Expire the token
        async def _expire():
            async with _test_session_factory() as db:
                result = await db.execute(
                    select(Session).where(Session.id == session_id)
                )
                session = result.scalar_one()
                session.last_message_at = datetime(
                    2020, 1, 1, tzinfo=timezone.utc
                )
                await db.commit()

        asyncio.get_event_loop().run_until_complete(_expire())

        client = TestClient(app)
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                f"/api/v1/ws/{session_id}?token={token}"
            ) as ws:
                pass


class TestWebSocketMessaging:
    """Tests for sending/receiving messages via WebSocket."""

    def test_send_message_and_receive_response(self):
        """Sending a guest message via WebSocket should produce an
        agent response with state info."""
        import asyncio

        session_id, token = asyncio.get_event_loop().run_until_complete(
            _create_test_session()
        )

        client = TestClient(app)
        with client.websocket_connect(
            f"/api/v1/ws/{session_id}?token={token}"
        ) as ws:
            # Consume welcome message
            ws.receive_text()

            # Send a guest message
            ws.send_text(json.dumps({"content": "I'd like to start"}))

            # Receive agent response
            raw = ws.receive_text()
            data = json.loads(raw)
            assert data["type"] == "agent"
            assert "message" in data["data"]
            assert data["data"]["message"]["role"] == "agent"
            assert "content" in data["data"]["message"]
            assert "current_state" in data["data"]
            assert "required_action" in data["data"]

    def test_invalid_message_format_returns_error(self):
        """Sending invalid JSON or message without 'content' should
        result in an error message, not a disconnect."""
        import asyncio

        session_id, token = asyncio.get_event_loop().run_until_complete(
            _create_test_session()
        )

        client = TestClient(app)
        with client.websocket_connect(
            f"/api/v1/ws/{session_id}?token={token}"
        ) as ws:
            # Consume welcome
            ws.receive_text()

            # Send invalid JSON
            ws.send_text("not json at all")
            raw = ws.receive_text()
            data = json.loads(raw)
            assert data["type"] == "error"

            # Send JSON without required 'content' field
            ws.send_text(json.dumps({"wrong_field": "hi"}))
            raw = ws.receive_text()
            data = json.loads(raw)
            assert data["type"] == "error"

            # Connection should still be alive — send valid message
            ws.send_text(json.dumps({"content": "hello"}))
            raw = ws.receive_text()
            data = json.loads(raw)
            assert data["type"] == "agent"


class TestWebSocketDisconnect:
    """Tests for disconnect and reconnect behavior."""

    def test_disconnect_removes_from_manager(self):
        """After disconnecting, the session should be removed from the
        active connections manager."""
        import asyncio

        session_id, token = asyncio.get_event_loop().run_until_complete(
            _create_test_session()
        )

        from app.api.websocket import manager

        client = TestClient(app)
        with client.websocket_connect(
            f"/api/v1/ws/{session_id}?token={token}"
        ) as ws:
            # Consume welcome
            ws.receive_text()
            # While connected, should be in the manager
            # (may or may not be depending on timing in TestClient)
            pass

        # After disconnect, the session should not be in active connections
        assert not manager.is_connected(session_id)

    @pytest.mark.asyncio
    async def test_reconnect_reflects_advanced_state(self):
        """After advancing state in one session, reconnecting should
        reflect the updated state. Tests the _process_guest_message
        logic directly (avoids TestClient threading issues with
        aiosqlite)."""
        session_id, token = await _create_test_session()

        from app.api.websocket import _process_guest_message

        # Advance state by processing a "start" message
        async with _test_session_factory() as db:
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session = result.scalar_one()
            response = await _process_guest_message(
                session, "start", db
            )

        assert response["current_state"] != "INIT"
        assert response["required_action"] is not None

        # Verify the session state was persisted
        async with _test_session_factory() as db:
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session = result.scalar_one()
            assert session.current_state != State.INIT.value

    @pytest.mark.asyncio
    async def test_message_persisted_to_db(self):
        """Messages exchanged via WebSocket should be persisted in
        the DB."""
        session_id, token = await _create_test_session()

        from app.api.websocket import _process_guest_message

        # Process a message
        async with _test_session_factory() as db:
            result = await db.execute(
                select(Session).where(Session.id == session_id)
            )
            session = result.scalar_one()
            await _process_guest_message(session, "I agree", db)

        # Check DB for persisted messages
        async with _test_session_factory() as db:
            result = await db.execute(
                select(Message)
                .where(Message.session_id == session_id)
                .order_by(Message.created_at.asc())
            )
            messages = result.scalars().all()

        roles = [m.role for m in messages]
        assert "guest" in roles
        assert "agent" in roles


class TestConnectionManager:
    """Unit tests for the ConnectionManager class."""

    def test_connect_and_disconnect(self):
        from app.api.websocket import ConnectionManager

        mgr = ConnectionManager()
        assert not mgr.is_connected("session-1")

    @pytest.mark.asyncio
    async def test_active_connections_dict(self):
        from app.api.websocket import ConnectionManager

        mgr = ConnectionManager()
        assert mgr.active_connections == {}

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self):
        """Sending to a non-connected session returns False."""
        from app.api.websocket import ConnectionManager

        mgr = ConnectionManager()
        result = await mgr.send_message("nonexistent", "hello")
        assert result is False

    @pytest.mark.asyncio
    async def test_broadcast_mixed(self):
        """Broadcast to mix of connected and non-connected sessions."""
        from app.api.websocket import ConnectionManager
        from unittest.mock import AsyncMock

        mgr = ConnectionManager()

        # Create a mock WebSocket
        mock_ws = AsyncMock()
        await mgr.connect("session-1", mock_ws)

        results = await mgr.broadcast(
            ["session-1", "session-2"], "test message"
        )
        assert results["session-1"] is True
        assert results["session-2"] is False

    @pytest.mark.asyncio
    async def test_connect_replaces_existing(self):
        """Connecting a session that already has a connection should
        close the old one."""
        from app.api.websocket import ConnectionManager
        from unittest.mock import AsyncMock

        mgr = ConnectionManager()
        old_ws = AsyncMock()
        new_ws = AsyncMock()

        await mgr.connect("session-1", old_ws)
        assert mgr.is_connected("session-1")

        await mgr.connect("session-1", new_ws)
        old_ws.close.assert_called_once()
        assert mgr.active_connections["session-1"] is new_ws
