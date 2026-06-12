"""Test API-002: Audit trail endpoint returns 401 for invalid API key.

Verifies that GET /api/v1/guests/{guest_id}/audit-trail returns HTTP 401
when an invalid (or missing) X-API-Key header is provided.
"""

import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.auth.api_key import get_api_key
from app.database import get_db


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mock_db_session():
    """A no-op async DB session so the test doesn't need a real database."""
    session = AsyncMock()
    return session


@pytest.fixture
def app_with_mock_db(mock_db_session):
    """FastAPI app with the DB dependency overridden to a mock session."""
    async def _override_get_db():
        yield mock_db_session

    app_dependency_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = _override_get_db
    yield app
    # Restore original overrides
    app.dependency_overrides = app_dependency_overrides


# ── 401 for invalid API key ────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_trail_401_invalid_api_key(app_with_mock_db, mock_db_session):
    """GET /api/v1/guests/{guest_id}/audit-trail returns 401 with an
    invalid X-API-Key header.

    The get_api_key dependency hashes the provided key and looks it up
    in the database. When the hash matches no active row, it raises
    HTTPException(401). We patch verify_api_key to return None (key not
    found) so the dependency rejects the request before any DB queries
    for the guest are executed.
    """
    with patch("app.auth.api_key.verify_api_key", return_value=None):
        transport = ASGITransport(app=app_with_mock_db)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/guests/guest-123/audit-trail",
                headers={"X-API-Key": "invalid-key-0000"},
            )

    assert response.status_code == 401, (
        f"Expected 401 for invalid API key, got {response.status_code}: "
        f"{response.text}"
    )
    body = response.json()
    assert "detail" in body, f"Response body missing 'detail': {body}"


@pytest.mark.asyncio
async def test_audit_trail_401_missing_api_key(app_with_mock_db, mock_db_session):
    """GET /api/v1/guests/{guest_id}/audit-trail returns 401 when the
    X-API-Key header is omitted entirely.

    The get_api_key dependency checks for a None header value and raises
    HTTPException(401) with 'X-API-Key header is required'.
    """
    transport = ASGITransport(app=app_with_mock_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/guests/guest-123/audit-trail",
            # No X-API-Key header at all
        )

    assert response.status_code == 401, (
        f"Expected 401 for missing API key, got {response.status_code}: "
        f"{response.text}"
    )
    body = response.json()
    assert "detail" in body, f"Response body missing 'detail': {body}"


@pytest.mark.asyncio
async def test_audit_trail_401_empty_api_key(app_with_mock_db, mock_db_session):
    """GET /api/v1/guests/{guest_id}/audit-trail returns 401 when the
    X-API-Key header is present but empty.

    An empty string is not None so it passes the first check, but its
    SHA-256 hash won't match any active row, so verify_api_key returns
    None and get_api_key raises 401.
    """
    with patch("app.auth.api_key.verify_api_key", return_value=None):
        transport = ASGITransport(app=app_with_mock_db)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/guests/guest-123/audit-trail",
                headers={"X-API-Key": ""},
            )

    assert response.status_code == 401, (
        f"Expected 401 for empty API key, got {response.status_code}: "
        f"{response.text}"
    )
    body = response.json()
    assert "detail" in body, f"Response body missing 'detail': {body}"
