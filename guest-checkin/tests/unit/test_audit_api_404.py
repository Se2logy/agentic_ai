"""Test API-003: Audit trail endpoint returns 404 for nonexistent guest.

TASK-005-013 / API-003

Verifies that GET /api/v1/guests/{guest_id}/audit-trail returns HTTP 404
when the guest_id does not exist in the database, even with valid API key auth.

The endpoint in app/api/audit.py explicitly checks for guest existence:
  - Queries Guest by guest_id
  - If scalar_one_or_none() returns None, raises HTTPException(404)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.auth.api_key import get_api_key
from app.database import get_db
from app.models.api_key import APIKey


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_api_key_obj():
    """A mock APIKey object to satisfy the get_api_key dependency."""
    key = MagicMock(spec=APIKey)
    key.id = "test-key-id"
    key.name = "test-key"
    key.is_active = True
    return key


@pytest.fixture
def mock_db_session():
    """A mock async DB session whose execute() returns configurable results."""
    session = AsyncMock()
    # By default, Guest lookup returns None (guest not found)
    guest_result = MagicMock()
    guest_result.scalar_one_or_none.return_value = None
    session.execute.return_value = guest_result
    return session


@pytest.fixture
def app_with_deps(mock_db_session, mock_api_key_obj):
    """FastAPI app with DB and API-key dependencies overridden."""
    async def _override_get_db():
        yield mock_db_session

    saved_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_api_key] = lambda: mock_api_key_obj
    yield app
    app.dependency_overrides = saved_overrides


# ── 404 for nonexistent guest ──────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_trail_404_nonexistent_guest(app_with_deps, mock_db_session):
    """GET /api/v1/guests/{guest_id}/audit-trail returns 404 when the
    guest_id does not exist in the database.

    With valid API key auth but a guest_id that has no matching row,
    the endpoint should raise HTTPException(status_code=404) with a
    detail message referencing the missing guest.
    """
    transport = ASGITransport(app=app_with_deps)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/guests/nonexistent-guest-id/audit-trail",
            headers={"X-API-Key": "valid-test-key"},
        )

    assert response.status_code == 404, (
        f"Expected 404 for nonexistent guest, got {response.status_code}: "
        f"{response.text}"
    )
    body = response.json()
    assert "detail" in body, f"Response body missing 'detail': {body}"
    assert "nonexistent-guest-id" in body["detail"], (
        f"Expected detail to reference the missing guest_id, got: {body['detail']}"
    )


@pytest.mark.asyncio
async def test_audit_trail_404_uuid_format_guest(app_with_deps, mock_db_session):
    """GET /api/v1/guests/{guest_id}/audit-trail returns 404 for a
    well-formed UUID that simply doesn't exist in the database.

    A valid UUID format but no matching row still yields 404.
    """
    fake_uuid = "00000000-0000-0000-0000-000000000000"
    transport = ASGITransport(app=app_with_deps)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/guests/{fake_uuid}/audit-trail",
            headers={"X-API-Key": "valid-test-key"},
        )

    assert response.status_code == 404, (
        f"Expected 404 for nonexistent UUID guest, got {response.status_code}: "
        f"{response.text}"
    )
    body = response.json()
    assert "detail" in body, f"Response body missing 'detail': {body}"
    assert fake_uuid in body["detail"], (
        f"Expected detail to reference the missing guest_id, got: {body['detail']}"
    )
