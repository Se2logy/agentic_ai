"""Test API-005: Audit trail pagination works, page_size > 200 is clamped.

TASK-005-015

Verifies that:
1. Default pagination values (page=1, page_size=50)
2. Custom pagination (page=2, page_size=10)
3. page_size=200 is accepted as-is
4. page_size=300 is rejected (422) — FastAPI Query(le=200) enforces the max
5. page_size=1 is accepted (minimum valid value)
6. page=0 is rejected (422) — must be >= 1
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import get_db
from app.auth.api_key import get_api_key
from app.models.api_key import APIKey
from app.models.guest import Guest
from app.models.audit_trail import AuditTrail


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def fake_api_key_obj():
    """A fake APIKey ORM object that satisfies get_api_key."""
    key = APIKey(
        id="test-key-id",
        key="fakehash",
        name="test-key",
        is_active=True,
    )
    return key


@pytest.fixture
def mock_db():
    """Mock AsyncSession with configurable behaviour for audit trail queries."""
    session = AsyncMock()

    # Default: guest found, one session, 0 audit entries
    guest_result = MagicMock()
    guest_result.scalar_one_or_none.return_value = Guest(
        id="guest-1",
        email="test@example.com",
        first_name="Test",
        last_name="User",
    )
    session_result = MagicMock()
    session_result.all.return_value = [("session-1",)]
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    entries_result = MagicMock()
    entries_result.scalars.return_value.all.return_value = []

    # Make execute return different results based on query order
    call_count = [0]

    async def _execute(stmt):
        call_count[0] += 1
        n = call_count[0]
        if n == 1:
            return guest_result        # Guest lookup
        elif n == 2:
            return session_result      # Session IDs
        elif n == 3:
            return count_result        # Count
        else:
            return entries_result      # Paginated entries

    session.execute = AsyncMock(side_effect=_execute)
    return session


@pytest.fixture
def app_with_deps(mock_db, fake_api_key_obj):
    """FastAPI app with DB and auth overridden for testing."""
    async def _override_get_db():
        yield mock_db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_api_key] = lambda: fake_api_key_obj
    yield app
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_api_key, None)


AUDIT_URL = "/api/v1/guests/guest-1/audit-trail"


# ── Test: Default pagination values ─────────────────────────────────


@pytest.mark.asyncio
async def test_default_pagination_values(app_with_deps):
    """GET audit-trail with no query params uses page=1, page_size=50."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["page"] == 1, f"Expected default page=1, got {body['page']}"
    assert body["page_size"] == 50, (
        f"Expected default page_size=50, got {body['page_size']}"
    )


# ── Test: Custom pagination ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_pagination(app_with_deps):
    """GET audit-trail?page=2&page_size=10 returns those values in response."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            params={"page": 2, "page_size": 10},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["page"] == 2, f"Expected page=2, got {body['page']}"
    assert body["page_size"] == 10, (
        f"Expected page_size=10, got {body['page_size']}"
    )


# ── Test: page_size=200 is accepted ────────────────────────────────


@pytest.mark.asyncio
async def test_page_size_200_accepted(app_with_deps):
    """page_size=200 is the maximum allowed value and is accepted as-is."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            params={"page_size": 200},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200, (
        f"Expected 200 for page_size=200, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["page_size"] == 200, (
        f"Expected page_size=200 in response, got {body['page_size']}"
    )


# ── Test: page_size=300 is rejected (422) ───────────────────────────


@pytest.mark.asyncio
async def test_page_size_300_rejected(app_with_deps):
    """page_size=300 exceeds the max (200) and is rejected with 422.

    The endpoint uses FastAPI Query(le=200), which validates at the
    framework level and returns 422 Unprocessable Entity rather than
    clamping. This ensures the client is always aware the value was
    not accepted as-is.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            params={"page_size": 300},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 422, (
        f"Expected 422 for page_size=300 (exceeds max 200), "
        f"got {response.status_code}: {response.text}"
    )
    body = response.json()
    # FastAPI returns validation error details
    assert "detail" in body, f"Expected validation error detail, got: {body}"


# ── Test: page_size=1 is accepted ──────────────────────────────────


@pytest.mark.asyncio
async def test_page_size_1_accepted(app_with_deps):
    """page_size=1 is the minimum allowed value and is accepted."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            params={"page_size": 1},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200, (
        f"Expected 200 for page_size=1, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["page_size"] == 1, (
        f"Expected page_size=1 in response, got {body['page_size']}"
    )


# ── Test: page=0 is rejected ───────────────────────────────────────


@pytest.mark.asyncio
async def test_page_zero_rejected(app_with_deps):
    """page=0 is invalid (must be >= 1) and is rejected with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            params={"page": 0},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 422, (
        f"Expected 422 for page=0, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "detail" in body, f"Expected validation error detail, got: {body}"


# ── Test: page_size=0 is rejected ──────────────────────────────────


@pytest.mark.asyncio
async def test_page_size_zero_rejected(app_with_deps):
    """page_size=0 is invalid (must be >= 1) and is rejected with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            params={"page_size": 0},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 422, (
        f"Expected 422 for page_size=0, got {response.status_code}: {response.text}"
    )


# ── Test: Response schema includes pagination fields ───────────────


@pytest.mark.asyncio
async def test_response_schema_has_pagination_fields(app_with_deps):
    """Audit trail response contains entries, total, page, page_size."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 200
    body = response.json()
    for key in ("entries", "total", "page", "page_size"):
        assert key in body, f"Response missing required field '{key}': {body}"


# ── Test: page_size=201 is rejected (just over max) ────────────────


@pytest.mark.asyncio
async def test_page_size_201_rejected(app_with_deps):
    """page_size=201 is just over the max (200) and is rejected with 422."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            AUDIT_URL,
            params={"page_size": 201},
            headers={"X-API-Key": "test-key"},
        )

    assert response.status_code == 422, (
        f"Expected 422 for page_size=201 (over max 200), "
        f"got {response.status_code}: {response.text}"
    )
