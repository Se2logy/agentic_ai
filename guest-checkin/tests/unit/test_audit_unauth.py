"""Test: Audit trail endpoint returns 401 for unauthenticated requests.

TASK-005-011 / API-001

Verifies that GET /api/v1/guests/{guest_id}/audit-trail returns HTTP 401
when no X-API-Key header is provided, and also when an invalid key is provided.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.database import get_db


@pytest.fixture
def override_db():
    """Override get_db with a mock AsyncSession so no real DB is needed."""

    mock_session = AsyncMock()
    # For verify_api_key: execute returns a result whose scalar_one_or_none returns None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    async def _fake_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = _fake_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_audit_trail_returns_401_without_api_key(override_db):
    """GET /api/v1/guests/{guest_id}/audit-trail without X-API-Key → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request WITHOUT X-API-Key header
        response = await client.get("/api/v1/guests/guest-123/audit-trail")

    assert response.status_code == 401, (
        f"Expected 401 for unauthenticated request, got {response.status_code}. "
        f"Body: {response.text}"
    )
    body = response.json()
    assert "detail" in body, f"Response missing 'detail' key: {body}"
    # The get_api_key dependency says "X-API-Key header is required" when missing
    assert "X-API-Key" in body["detail"], (
        f"Expected detail to mention X-API-Key, got: {body['detail']}"
    )


@pytest.mark.asyncio
async def test_audit_trail_returns_401_with_invalid_api_key(override_db):
    """GET /api/v1/guests/{guest_id}/audit-trail with invalid X-API-Key → 401."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Request WITH an invalid X-API-Key header
        response = await client.get(
            "/api/v1/guests/guest-123/audit-trail",
            headers={"X-API-Key": "this-is-not-a-valid-key"},
        )

    assert response.status_code == 401, (
        f"Expected 401 for invalid API key, got {response.status_code}. "
        f"Body: {response.text}"
    )
    body = response.json()
    assert "detail" in body, f"Response missing 'detail' key: {body}"
    # verify_api_key returns None for unknown key → "Invalid or inactive API key"
    assert "Invalid" in body["detail"] or "inactive" in body["detail"], (
        f"Expected detail to mention invalid/inactive key, got: {body['detail']}"
    )
