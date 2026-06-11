"""Test API-004: Audit trail response shape matches AuditTrailResponse schema.

TASK-005-014

Verifies that the audit trail endpoint returns data matching the AuditTrailResponse
schema: entries list with from_state (str), to_state (str), timestamp (datetime),
actor (str); plus total (int), page (int), page_size (int) at the top level.

Uses httpx AsyncClient with dependency overrides to exercise the real endpoint
without a live database, then validates the response body against the Pydantic
schema and checks field types/structure.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.main import app
from app.auth.api_key import get_api_key
from app.database import get_db
from app.schemas.audit import AuditTrailEntry, AuditTrailResponse
from app.models.audit_trail import AuditTrail
from app.models.guest import Guest
from app.models.session import Session


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_api_key_obj():
    """A mock APIKey that passes the get_api_key dependency."""
    key = MagicMock()
    key.id = "test-key-id"
    key.name = "test-key"
    key.is_active = True
    return key


@pytest.fixture
def mock_guest():
    """A mock Guest row."""
    guest = MagicMock(spec=Guest)
    guest.id = "guest-abc"
    guest.email = "alice@example.com"
    return guest


@pytest.fixture
def mock_session_row():
    """A mock Session row."""
    session = MagicMock(spec=Session)
    session.id = "session-001"
    return session


@pytest.fixture
def mock_audit_rows():
    """Two mock AuditTrail rows (newest first)."""
    row1 = MagicMock(spec=AuditTrail)
    row1.from_state = "INIT"
    row1.to_state = "PRIVACY_POLICY_PENDING"
    row1.created_at = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)
    row1.actor = "guest"

    row2 = MagicMock(spec=AuditTrail)
    row2.from_state = "PRIVACY_POLICY_PENDING"
    row2.to_state = "HOUSE_RULES_PENDING"
    row2.created_at = datetime(2024, 6, 15, 10, 5, 0, tzinfo=timezone.utc)
    row2.actor = "system"

    return [row2, row1]  # DESC order as the endpoint returns


def _build_overrides(mock_api_key_obj, mock_guest, mock_session_row, mock_audit_rows):
    """Build dependency overrides for the FastAPI app so the endpoint runs
    without a real database.

    The endpoint does three DB queries:
      1. SELECT Guest WHERE id = guest_id  → returns mock_guest
      2. SELECT Session.id WHERE guest_id  → returns [mock_session_row.id]
      3a. SELECT count(*) ...               → returns 2
      3b. SELECT AuditTrail ... ORDER/limit → returns mock_audit_rows
    """
    mock_db = AsyncMock()

    # First call: guest lookup
    guest_result = MagicMock()
    guest_result.scalar_one_or_none.return_value = mock_guest

    # Second call: session ids
    session_result = MagicMock()
    session_result.all.return_value = [(mock_session_row.id,)]

    # Third call: count
    count_result = MagicMock()
    count_result.scalar.return_value = 2

    # Fourth call: paginated audit rows
    audit_result = MagicMock()
    audit_result.scalars.return_value.all.return_value = mock_audit_rows

    # The endpoint calls `await db.execute(...)` four times
    mock_db.execute.side_effect = [
        guest_result,
        session_result,
        count_result,
        audit_result,
    ]

    async def _override_get_db():
        yield mock_db

    return {
        get_api_key: lambda: mock_api_key_obj,
        get_db: _override_get_db,
    }


# ── Tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_trail_response_shape_matches_schema(
    mock_api_key_obj, mock_guest, mock_session_row, mock_audit_rows
):
    """API-004: The endpoint response body must be deserialisable as
    AuditTrailResponse, with all required fields and correct types."""

    overrides = _build_overrides(
        mock_api_key_obj, mock_guest, mock_session_row, mock_audit_rows
    )
    saved = app.dependency_overrides.copy()
    app.dependency_overrides.update(overrides)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/guests/guest-abc/audit-trail",
                headers={"X-API-Key": "test-key"},
            )
    finally:
        app.dependency_overrides = saved

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    body = response.json()

    # ── Top-level AuditTrailResponse fields ─────────────────────────
    # Must validate through Pydantic — proves shape is correct
    parsed = AuditTrailResponse.model_validate(body)
    assert isinstance(parsed, AuditTrailResponse)

    # Required top-level fields with correct types
    assert isinstance(parsed.entries, list), "entries must be a list"
    assert isinstance(parsed.total, int), "total must be int"
    assert isinstance(parsed.page, int), "page must be int"
    assert isinstance(parsed.page_size, int), "page_size must be int"

    # ── AuditTrailEntry shape within entries ────────────────────────
    assert len(parsed.entries) == 2, f"Expected 2 entries, got {len(parsed.entries)}"

    for entry in parsed.entries:
        assert isinstance(entry, AuditTrailEntry), f"Entry is not AuditTrailEntry: {type(entry)}"

        # from_state: str
        assert isinstance(entry.from_state, str), f"from_state must be str, got {type(entry.from_state)}"

        # to_state: str
        assert isinstance(entry.to_state, str), f"to_state must be str, got {type(entry.to_state)}"

        # timestamp: datetime
        assert isinstance(entry.timestamp, datetime), f"timestamp must be datetime, got {type(entry.timestamp)}"

        # actor: str
        assert isinstance(entry.actor, str), f"actor must be str, got {type(entry.actor)}"

    # ── Specific values from our mock data ──────────────────────────
    # Rows are returned newest-first: row2 (HOUSE_RULES) then row1 (PRIVACY_POLICY)
    first = parsed.entries[0]
    assert first.from_state == "PRIVACY_POLICY_PENDING"
    assert first.to_state == "HOUSE_RULES_PENDING"
    assert first.actor == "system"

    second = parsed.entries[1]
    assert second.from_state == "INIT"
    assert second.to_state == "PRIVACY_POLICY_PENDING"
    assert second.actor == "guest"

    # Pagination fields
    assert parsed.total == 2
    assert parsed.page == 1
    assert parsed.page_size == 50


@pytest.mark.asyncio
async def test_audit_trail_empty_guest_sessions(
    mock_api_key_obj, mock_guest,
):
    """API-004: When a guest has no sessions, the endpoint returns a valid
    AuditTrailResponse with an empty entries list."""

    mock_db = AsyncMock()

    # Guest exists
    guest_result = MagicMock()
    guest_result.scalar_one_or_none.return_value = mock_guest

    # No sessions found
    session_result = MagicMock()
    session_result.all.return_value = []

    mock_db.execute.side_effect = [guest_result, session_result]

    async def _override_get_db():
        yield mock_db

    saved = app.dependency_overrides.copy()
    app.dependency_overrides.update({
        get_api_key: lambda: mock_api_key_obj,
        get_db: _override_get_db,
    })
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/guests/guest-abc/audit-trail",
                headers={"X-API-Key": "test-key"},
            )
    finally:
        app.dependency_overrides = saved

    assert response.status_code == 200
    body = response.json()

    # Must validate as AuditTrailResponse
    parsed = AuditTrailResponse.model_validate(body)
    assert parsed.entries == []
    assert parsed.total == 0
    assert parsed.page == 1
    assert parsed.page_size == 50


@pytest.mark.asyncio
async def test_audit_trail_pagination_params_in_response(
    mock_api_key_obj, mock_guest, mock_session_row, mock_audit_rows,
):
    """API-004: page and page_size query params are echoed in the response
    and typed as int."""

    mock_db = AsyncMock()

    guest_result = MagicMock()
    guest_result.scalar_one_or_none.return_value = mock_guest

    session_result = MagicMock()
    session_result.all.return_value = [(mock_session_row.id,)]

    count_result = MagicMock()
    count_result.scalar.return_value = 42

    audit_result = MagicMock()
    audit_result.scalars.return_value.all.return_value = mock_audit_rows

    mock_db.execute.side_effect = [guest_result, session_result, count_result, audit_result]

    async def _override_get_db():
        yield mock_db

    saved = app.dependency_overrides.copy()
    app.dependency_overrides.update({
        get_api_key: lambda: mock_api_key_obj,
        get_db: _override_get_db,
    })
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/guests/guest-abc/audit-trail",
                params={"page": 2, "page_size": 10},
                headers={"X-API-Key": "test-key"},
            )
    finally:
        app.dependency_overrides = saved

    assert response.status_code == 200
    body = response.json()
    parsed = AuditTrailResponse.model_validate(body)

    assert parsed.page == 2, f"page should be 2, got {parsed.page}"
    assert parsed.page_size == 10, f"page_size should be 10, got {parsed.page_size}"
    assert parsed.total == 42, f"total should be 42, got {parsed.total}"
    assert isinstance(parsed.entries, list)


class TestAuditTrailEntryFieldCompleteness:
    """API-004: AuditTrailEntry has the fields: id, session_id, action,
    from_state, to_state, details, timestamp, actor."""

    def test_entry_has_required_fields(self):
        """AuditTrailEntry must define id, session_id, action, from_state, to_state, details, timestamp, actor."""
        expected = {"id", "session_id", "action", "from_state", "to_state", "details", "timestamp", "actor"}
        actual = set(AuditTrailEntry.model_fields.keys())
        assert expected.issubset(actual), (
            f"AuditTrailEntry missing fields: {expected - actual}"
        )

    def test_response_has_required_fields(self):
        """AuditTrailResponse must define entries, total, page, page_size."""
        expected = {"entries", "total", "page", "page_size"}
        actual = set(AuditTrailResponse.model_fields.keys())
        assert expected.issubset(actual), (
            f"AuditTrailResponse missing fields: {expected - actual}"
        )

    def test_entry_fields_are_correct_types(self):
        """Verify the field type annotations on AuditTrailEntry."""
        fields = AuditTrailEntry.model_fields
        # id: str
        assert "str" in str(fields["id"].annotation).lower() or fields["id"].annotation is str
        # session_id: str
        assert "str" in str(fields["session_id"].annotation).lower() or fields["session_id"].annotation is str
        # action: str
        assert "str" in str(fields["action"].annotation).lower() or fields["action"].annotation is str
        # from_state: str | None
        assert "str" in str(fields["from_state"].annotation).lower() or fields["from_state"].annotation is str
        # to_state: str | None
        assert "str" in str(fields["to_state"].annotation).lower() or fields["to_state"].annotation is str
        # timestamp: datetime
        assert "datetime" in str(fields["timestamp"].annotation).lower()
        # actor: str
        assert "str" in str(fields["actor"].annotation).lower() or fields["actor"].annotation is str

    def test_response_fields_are_correct_types(self):
        """Verify the field type annotations on AuditTrailResponse."""
        fields = AuditTrailResponse.model_fields
        # entries: list
        assert "list" in str(fields["entries"].annotation).lower()
        # total: int
        assert "int" in str(fields["total"].annotation).lower()
        # page: int
        assert "int" in str(fields["page"].annotation).lower()
        # page_size: int
        assert "int" in str(fields["page_size"].annotation).lower()
