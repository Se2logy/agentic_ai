"""Integration test: Full seeded audit trail flow (API-006 / TASK-005-016).

Verifies the complete data path:
  ORM model → log_audit → DB → SQLAlchemy query → Pydantic serialization → HTTP response

Uses SQLite in-memory with real SQLAlchemy async session to exercise the
full stack without requiring MySQL.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.api_key import APIKey
from app.models.audit_trail import AuditTrail
from app.models.guest import Guest
from app.models.reservation import Reservation
from app.models.session import Session
from app.state_machine.audit import log_audit
from app.state_machine.states import State
from app.auth.api_key import _hash_api_key
from app.database import get_db
from app.auth.api_key import get_api_key

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


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def _setup_db():
    """Create all tables before each test, drop after."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def app_with_overrides():
    """FastAPI app with get_db and get_api_key overridden for testing."""
    from app.main import app

    # Real-looking API key object for auth override
    api_key_obj = APIKey(
        id=str(uuid.uuid4()),
        key=_hash_api_key("test-api-key"),
        name="test-integration-key",
        is_active=True,
    )

    async def _override_get_db():
        async with _test_session_factory() as session:
            yield session

    async def _override_get_api_key():
        return api_key_obj

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_api_key] = _override_get_api_key

    yield app

    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_api_key, None)


# ── Seed helper ──────────────────────────────────────────────────────

async def _seed_guest_and_session() -> tuple[str, str]:
    """Create a Guest, Reservation, Session in the test DB.
    Returns (guest_id, session_id).
    """
    async with _test_session_factory() as db:
        guest = Guest(
            email=f"audit-test-{uuid.uuid4().hex[:8]}@example.com",
            first_name="Audit",
            last_name="Tester",
            phone="+1555000000",
        )
        db.add(guest)
        await db.flush()

        reservation = Reservation(
            booking_reference=f"BK-AUDIT-{uuid.uuid4().hex[:8]}",
            property_name="Audit Hotel",
            property_address="1 Audit Street",
            guest_name="Audit Tester",
            guest_email=guest.email,
            check_in_date=date(2025, 7, 1),
            check_out_date=date(2025, 7, 7),
            num_guests=1,
            house_rules_text="No noise after 10pm",
            rental_agreement_text="Standard terms",
            privacy_policy_text="We respect your privacy",
        )
        db.add(reservation)
        await db.flush()

        session = Session(
            reservation_id=reservation.id,
            guest_id=guest.id,
            session_token=f"tok-{uuid.uuid4().hex[:16]}",
            current_state=State.INIT.value,
            status="active",
            last_message_at=datetime.now(timezone.utc),
        )
        db.add(session)
        await db.flush()

        await db.commit()
        return guest.id, session.id


async def _seed_audit_entries(session_id: str) -> list[dict]:
    """Create audit entries via log_audit to exercise the full write path.
    Explicitly sets distinct created_at timestamps on each entry to ensure
    deterministic ordering (SQLite CURRENT_TIMESTAMP has only second-level
    precision, so entries created within the same second would be unordered).

    Returns a list of dicts describing the seeded entries in insertion order.
    """
    transitions = [
        (None, State.PRIVACY_POLICY_PENDING, "advance", "system"),
        (State.PRIVACY_POLICY_PENDING, State.HOUSE_RULES_PENDING, "advance", "guest"),
        (State.HOUSE_RULES_PENDING, State.RENTAL_AGREEMENT_PENDING, "advance", "guest"),
        (State.RENTAL_AGREEMENT_PENDING, State.INFO_VERIFY_PENDING, "advance", "guest"),
        (State.INFO_VERIFY_PENDING, State.ID_VERIFY_PENDING, "advance", "system"),
    ]

    base_time = datetime(2025, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
    entries_created = []

    async with _test_session_factory() as db:
        for i, (from_state, to_state, action, actor) in enumerate(transitions):
            entry = await log_audit(
                db_session=db,
                session_id=session_id,
                action=action,
                from_state=from_state,
                to_state=to_state,
                details={"source": "integration_test"},
                actor=actor,
            )
            # Override created_at to ensure deterministic ordering
            entry.created_at = base_time + timedelta(minutes=i)
            await db.commit()
            entries_created.append(entry)

    # Return metadata for verification (in insertion order)
    return [
        {
            "from_state": fs.value if fs else "",
            "to_state": ts.value,
            "action": a,
            "actor": ac,
        }
        for fs, ts, a, ac in transitions
    ]


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_seeded_audit_trail_flow(app_with_overrides):
    """API-006: Full seeded audit trail flow.

    Seeds a guest session and audit entries using log_audit,
    then calls GET /api/v1/guests/{guest_id}/audit-trail and
    verifies:
      1. Response structure matches AuditTrailResponse schema
      2. Entries contain the correct state transitions
      3. Ordering is created_at DESC (newest first)
      4. Pagination metadata is correct
    """
    from httpx import ASGITransport, AsyncClient

    # ── Seed data ──
    guest_id, session_id = await _seed_guest_and_session()
    transition_meta = await _seed_audit_entries(session_id)

    # ── Call the endpoint ──
    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/guests/{guest_id}/audit-trail",
            headers={"X-API-Key": "test-api-key"},
        )

    # ── Verify HTTP 200 ──
    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )

    body = response.json()

    # ── Verify response structure ──
    assert "entries" in body, f"Missing 'entries' key: {body}"
    assert "total" in body, f"Missing 'total' key: {body}"
    assert "page" in body, f"Missing 'page' key: {body}"
    assert "page_size" in body, f"Missing 'page_size' key: {body}"

    # ── Verify entry count and total ──
    num_seeded = len(transition_meta)
    assert body["total"] == num_seeded, (
        f"Expected total={num_seeded}, got {body['total']}"
    )
    assert len(body["entries"]) == num_seeded, (
        f"Expected {num_seeded} entries, got {len(body['entries'])}"
    )

    # ── Verify pagination defaults ──
    assert body["page"] == 1, f"Expected page=1, got {body['page']}"
    assert body["page_size"] == 50, f"Expected page_size=50, got {body['page_size']}"

    # ── Verify each entry has required schema fields ──
    for entry in body["entries"]:
        assert "from_state" in entry, f"Entry missing 'from_state': {entry}"
        assert "to_state" in entry, f"Entry missing 'to_state': {entry}"
        assert "timestamp" in entry, f"Entry missing 'timestamp': {entry}"
        assert "actor" in entry, f"Entry missing 'actor': {entry}"

    # ── Verify state transitions match seeded data ──
    # Response is DESC (newest first), so reverse to compare with insertion order
    response_entries = list(reversed(body["entries"]))
    for i, (expected, actual) in enumerate(zip(transition_meta, response_entries)):
        assert actual["from_state"] == expected["from_state"], (
            f"Entry {i}: expected from_state={expected['from_state']!r}, "
            f"got {actual['from_state']!r}"
        )
        assert actual["to_state"] == expected["to_state"], (
            f"Entry {i}: expected to_state={expected['to_state']!r}, "
            f"got {actual['to_state']!r}"
        )
        assert actual["actor"] == expected["actor"], (
            f"Entry {i}: expected actor={expected['actor']!r}, "
            f"got {actual['actor']!r}"
        )

    # ── Verify ordering: created_at DESC (newest first) ──
    # The last seeded entry (INFO_VERIFY_PENDING → ID_VERIFY_PENDING) should appear first
    last_transition = transition_meta[-1]
    first_entry = body["entries"][0]
    assert first_entry["from_state"] == last_transition["from_state"], (
        f"First entry should be the newest. Expected from_state="
        f"{last_transition['from_state']!r}, got {first_entry['from_state']!r}"
    )
    assert first_entry["to_state"] == last_transition["to_state"], (
        f"First entry should be the newest. Expected to_state="
        f"{last_transition['to_state']!r}, got {first_entry['to_state']!r}"
    )

    # Also verify timestamps are strictly descending
    timestamps = [e["timestamp"] for e in body["entries"]]
    for j in range(len(timestamps) - 1):
        assert timestamps[j] >= timestamps[j + 1], (
            f"Entries not in DESC order: entry[{j}].timestamp ({timestamps[j]}) "
            f"< entry[{j+1}].timestamp ({timestamps[j+1]})"
        )


@pytest.mark.asyncio
async def test_audit_trail_empty_for_guest_with_no_sessions(app_with_overrides):
    """API-006: Guest exists but has no sessions → empty audit trail."""
    from httpx import ASGITransport, AsyncClient

    # Create a guest with no sessions
    async with _test_session_factory() as db:
        guest = Guest(
            email=f"no-session-{uuid.uuid4().hex[:8]}@example.com",
            first_name="No",
            last_name="Sessions",
        )
        db.add(guest)
        await db.commit()
        guest_id = guest.id

    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/guests/{guest_id}/audit-trail",
            headers={"X-API-Key": "test-api-key"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["entries"] == []
    assert body["total"] == 0


@pytest.mark.asyncio
async def test_audit_trail_guest_not_found(app_with_overrides):
    """API-006: Non-existent guest_id → 404."""
    from httpx import ASGITransport, AsyncClient

    fake_guest_id = str(uuid.uuid4())

    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/guests/{fake_guest_id}/audit-trail",
            headers={"X-API-Key": "test-api-key"},
        )

    assert response.status_code == 404, (
        f"Expected 404 for non-existent guest, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "detail" in body
    assert "not found" in body["detail"].lower() or fake_guest_id in body["detail"]


@pytest.mark.asyncio
async def test_audit_trail_pagination(app_with_overrides):
    """API-006: Pagination works — page 1 with page_size=2 returns 2 entries."""
    from httpx import ASGITransport, AsyncClient

    guest_id, session_id = await _seed_guest_and_session()
    transition_meta = await _seed_audit_entries(session_id)

    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/guests/{guest_id}/audit-trail",
            params={"page": 1, "page_size": 2},
            headers={"X-API-Key": "test-api-key"},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 2, f"Expected 2 entries on page 1, got {len(body['entries'])}"
    assert body["total"] == len(transition_meta), f"Expected total={len(transition_meta)}, got {body['total']}"
    assert body["page"] == 1
    assert body["page_size"] == 2

    # First entry on page 1 should be the newest (DESC order)
    newest = transition_meta[-1]
    assert body["entries"][0]["from_state"] == newest["from_state"]
    assert body["entries"][0]["to_state"] == newest["to_state"]

    # ── Page 2 ──
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response2 = await client.get(
            f"/api/v1/guests/{guest_id}/audit-trail",
            params={"page": 2, "page_size": 2},
            headers={"X-API-Key": "test-api-key"},
        )

    assert response2.status_code == 200
    body2 = response2.json()
    assert len(body2["entries"]) == 2, f"Expected 2 entries on page 2, got {len(body2['entries'])}"
    assert body2["page"] == 2

    # Entries on page 2 should be older than page 1 entries
    page1_timestamps = [e["timestamp"] for e in body["entries"]]
    page2_timestamps = [e["timestamp"] for e in body2["entries"]]
    assert page1_timestamps[-1] >= page2_timestamps[0], (
        "Page 2 entries should be older than page 1 entries"
    )


@pytest.mark.asyncio
async def test_audit_trail_from_state_null_serialized_as_empty_string(app_with_overrides):
    """API-006: First audit entry has from_state=None in DB → serialized as '' in response."""
    from httpx import ASGITransport, AsyncClient

    guest_id, session_id = await _seed_guest_and_session()

    # Seed only the first transition (from_state=None → PRIVACY_POLICY_PENDING)
    async with _test_session_factory() as db:
        entry = await log_audit(
            db_session=db,
            session_id=session_id,
            action="advance",
            from_state=None,
            to_state=State.PRIVACY_POLICY_PENDING,
            actor="system",
        )
        entry.created_at = datetime(2025, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
        await db.commit()

    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/guests/{guest_id}/audit-trail",
            headers={"X-API-Key": "test-api-key"},
        )

    assert response.status_code == 200
    body = response.json()
    assert len(body["entries"]) == 1
    # from_state is None in DB → serialized as "" per the endpoint code
    assert body["entries"][0]["from_state"] == "", (
        f"Expected from_state='' for None, got {body['entries'][0]['from_state']!r}"
    )
    assert body["entries"][0]["to_state"] == "PRIVACY_POLICY_PENDING"


@pytest.mark.asyncio
async def test_audit_trail_multiple_sessions_for_same_guest(app_with_overrides):
    """API-006: Guest with multiple sessions → audit trail aggregates all sessions."""
    from httpx import ASGITransport, AsyncClient

    # Create guest and first session
    guest_id, session1_id = await _seed_guest_and_session()

    # Seed audit entries in session 1
    transition_meta = await _seed_audit_entries(session1_id)

    # Create a second session for the same guest
    async with _test_session_factory() as db:
        guest_result = await db.execute(
            select(Guest).where(Guest.id == guest_id)
        )
        guest = guest_result.scalar_one()

        reservation2 = Reservation(
            booking_reference=f"BK-AUDIT2-{uuid.uuid4().hex[:8]}",
            property_name="Audit Hotel 2",
            property_address="2 Audit Lane",
            guest_name=guest.first_name + " " + guest.last_name,
            guest_email=guest.email,
            check_in_date=date(2025, 8, 1),
            check_out_date=date(2025, 8, 7),
            num_guests=1,
            house_rules_text="No noise",
            rental_agreement_text="Standard",
            privacy_policy_text="Privacy",
        )
        db.add(reservation2)
        await db.flush()

        session2 = Session(
            reservation_id=reservation2.id,
            guest_id=guest_id,
            session_token=f"tok2-{uuid.uuid4().hex[:16]}",
            current_state=State.INIT.value,
            status="active",
            last_message_at=datetime.now(timezone.utc),
        )
        db.add(session2)
        await db.flush()
        await db.commit()
        session2_id = session2.id

    # Seed one entry in session 2 with a distinct later timestamp
    async with _test_session_factory() as db:
        entry = await log_audit(
            db_session=db,
            session_id=session2_id,
            action="advance",
            from_state=None,
            to_state=State.PRIVACY_POLICY_PENDING,
            actor="guest",
        )
        # Set a later timestamp so it appears first in DESC ordering
        entry.created_at = datetime(2025, 7, 1, 11, 0, 0, tzinfo=timezone.utc)
        await db.commit()

    transport = ASGITransport(app=app_with_overrides)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/guests/{guest_id}/audit-trail",
            headers={"X-API-Key": "test-api-key"},
        )

    assert response.status_code == 200
    body = response.json()
    # 5 entries from session 1 + 1 from session 2 = 6 total
    assert body["total"] == 6, f"Expected total=6, got {body['total']}"
    assert len(body["entries"]) == 6
    # The session 2 entry should be first (latest timestamp)
    assert body["entries"][0]["from_state"] == ""
    assert body["entries"][0]["to_state"] == "PRIVACY_POLICY_PENDING"
