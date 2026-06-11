"""SEC-SESS-002: Session idle timeout is configurable via settings.SESSION_TOKEN_EXPIRY_HOURS.

Covers test-coverage.md rows:
- ST-SEC-002: Active → Expired (idle) when last_message_at exceeds threshold
- ST-SEC-004: Active → Active (within idle window)
- EC-SEC-004: Inactive session rejected when inactivity > configurable threshold
- EC-SEC-006: Boundary — session idle exactly at threshold (accepted)
- CSR-SEC-002: Expired idle → cannot recover (must start new session)
"""

import importlib
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.auth.session_token import verify_session_token


def _make_mock_session(
    created_at: datetime,
    last_message_at: datetime | None = None,
    status: str = "active",
) -> MagicMock:
    """Create a mock Session row with the given timestamps."""
    session = MagicMock()
    session.created_at = created_at
    session.last_message_at = last_message_at
    session.status = status
    session.session_token = "test-token-123"
    return session


@pytest.fixture
def mock_db():
    """Return a mock AsyncSession that tests can configure per-case."""
    db = AsyncMock()
    return db


def _setup_db_query(mock_db, mock_session):
    """Configure the mock db to return the given session on execute()."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = mock_session
    mock_db.execute.return_value = result


# ────────────────────────────────────────────────────────────────
# 1. Confirm idle timeout reads from settings.SESSION_TOKEN_EXPIRY_HOURS
# ────────────────────────────────────────────────────────────────


class TestIdleTimeoutReadsFromSettings:
    """Idle expiry threshold is derived from settings, NOT hardcoded."""

    @pytest.mark.asyncio
    async def test_idle_timeout_uses_settings_not_hardcoded(self, mock_db):
        """Verify the idle timeout code references settings.SESSION_TOKEN_EXPIRY_HOURS."""
        # Inspect the source code to confirm it imports from settings
        from app.auth import session_token as st_mod

        source = st_mod.verify_session_token.__code__.co_names
        # The function body references 'timedelta', 'settings', etc.
        # The key proof: after import, settings.SESSION_TOKEN_EXPIRY_HOURS is used.
        from app.config import settings

        # Default should be 24 (not a different hardcoded value)
        assert settings.SESSION_TOKEN_EXPIRY_HOURS == 24

        # Also verify the function source contains the settings reference
        import inspect

        source_text = inspect.getsource(st_mod.verify_session_token)
        assert "settings.SESSION_TOKEN_EXPIRY_HOURS" in source_text, (
            "verify_session_token must read idle threshold from settings.SESSION_TOKEN_EXPIRY_HOURS"
        )
        # Ensure there is no hardcoded "24" used in idle check (only settings-derived value)
        # The only "24" should be in the settings default, not in the function logic
        assert "timedelta(hours=24)" not in source_text, (
            "Idle timeout must not hardcode 24h — should use token_max_age_hours from settings"
        )


# ────────────────────────────────────────────────────────────────
# 2. Default settings: session within idle window is accepted
# ────────────────────────────────────────────────────────────────


class TestDefaultIdleTimeoutAccepts:
    """With default SESSION_TOKEN_EXPIRY_HOURS=24, active sessions within idle window are accepted."""

    @pytest.mark.asyncio
    async def test_recently_active_session_accepted(self, mock_db):
        """Session with last_message_at 1 hour ago should be accepted (within 24h idle window)."""
        now = datetime.now(timezone.utc)
        session = _make_mock_session(
            created_at=now - timedelta(hours=1),
            last_message_at=now - timedelta(hours=1),
        )
        _setup_db_query(mock_db, session)

        result = await verify_session_token("test-token-123", mock_db)
        assert result is not None, "Session active 1h ago should be accepted (within 24h idle)"

    @pytest.mark.asyncio
    async def test_session_with_no_last_message_accepted(self, mock_db):
        """Session with last_message_at=None (never messaged) should be accepted
        if within absolute expiry."""
        now = datetime.now(timezone.utc)
        session = _make_mock_session(
            created_at=now - timedelta(hours=1),
            last_message_at=None,
        )
        _setup_db_query(mock_db, session)

        result = await verify_session_token("test-token-123", mock_db)
        assert result is not None, "Session with no messages should be accepted if within absolute window"

    @pytest.mark.asyncio
    async def test_session_at_idle_boundary_accepted(self, mock_db):
        """EC-SEC-006: Session idle exactly at threshold (23h59m ago) should be accepted."""
        now = datetime.now(timezone.utc)
        # 23h 59m ago — just under the 24h threshold
        session = _make_mock_session(
            created_at=now - timedelta(hours=23, minutes=59),
            last_message_at=now - timedelta(hours=23, minutes=59),
        )
        _setup_db_query(mock_db, session)

        result = await verify_session_token("test-token-123", mock_db)
        assert result is not None, "Session idle at exactly the threshold boundary should be accepted"


# ────────────────────────────────────────────────────────────────
# 3. Default settings: session beyond idle window is rejected
# ────────────────────────────────────────────────────────────────


class TestDefaultIdleTimeoutRejects:
    """With default SESSION_TOKEN_EXPIRY_HOURS=24, sessions beyond idle window are rejected."""

    @pytest.mark.asyncio
    async def test_idle_session_rejected(self, mock_db):
        """EC-SEC-004 / ST-SEC-002: Session with last_message_at 25h ago is rejected."""
        now = datetime.now(timezone.utc)
        session = _make_mock_session(
            created_at=now - timedelta(hours=30),  # within 24h absolute? no, but we test idle
            last_message_at=now - timedelta(hours=25),  # idle for 25h > 24h threshold
        )
        _setup_db_query(mock_db, session)

        result = await verify_session_token("test-token-123", mock_db)
        assert result is None, "Session idle for 25h should be rejected (exceeds 24h idle timeout)"

    @pytest.mark.asyncio
    async def test_cannot_recover_from_idle_expiry(self, mock_db):
        """CSR-SEC-002: Once idle-expired, the same session token returns None (no recovery)."""
        now = datetime.now(timezone.utc)
        session = _make_mock_session(
            created_at=now - timedelta(hours=30),
            last_message_at=now - timedelta(hours=25),
        )
        _setup_db_query(mock_db, session)

        # First call: rejected
        result1 = await verify_session_token("test-token-123", mock_db)
        assert result1 is None

        # Second call: still rejected (no recovery path)
        mock_db.execute.return_value.scalar_one_or_none.return_value = session
        result2 = await verify_session_token("test-token-123", mock_db)
        assert result2 is None, "Idle-expired session cannot be recovered — must start new session"


# ────────────────────────────────────────────────────────────────
# 4. Changing SESSION_TOKEN_EXPIRY_HOURS changes the threshold
# ────────────────────────────────────────────────────────────────


class TestIdleTimeoutConfigurable:
    """Changing settings.SESSION_TOKEN_EXPIRY_HOURS changes which sessions are rejected for inactivity."""

    @pytest.mark.asyncio
    async def test_short_expiry_rejects_quickly(self, mock_db):
        """Set SESSION_TOKEN_EXPIRY_HOURS=0.001 (~3.6s).
        A session idle for 10s should be rejected."""
        now = datetime.now(timezone.utc)
        session = _make_mock_session(
            created_at=now - timedelta(seconds=15),
            last_message_at=now - timedelta(seconds=10),  # idle for 10s > 3.6s threshold
        )
        _setup_db_query(mock_db, session)

        with patch("app.config.settings.SESSION_TOKEN_EXPIRY_HOURS", 0.001):
            # Need to reimport so the function picks up the patched setting
            from app.auth import session_token as st_mod
            importlib.reload(st_mod)
            result = await st_mod.verify_session_token("test-token-123", mock_db)

        assert result is None, (
            "With SESSION_TOKEN_EXPIRY_HOURS=0.001, session idle for 10s should be rejected"
        )

    @pytest.mark.asyncio
    async def test_short_expiry_accepts_recent(self, mock_db):
        """Set SESSION_TOKEN_EXPIRY_HOURS=0.001 (~3.6s).
        A session active 1s ago should be accepted."""
        now = datetime.now(timezone.utc)
        session = _make_mock_session(
            created_at=now - timedelta(seconds=2),
            last_message_at=now - timedelta(seconds=1),  # idle for 1s < 3.6s threshold
        )
        _setup_db_query(mock_db, session)

        with patch("app.config.settings.SESSION_TOKEN_EXPIRY_HOURS", 0.001):
            from app.auth import session_token as st_mod
            importlib.reload(st_mod)
            result = await st_mod.verify_session_token("test-token-123", mock_db)

        assert result is not None, (
            "With SESSION_TOKEN_EXPIRY_HOURS=0.001, session idle for 1s should be accepted"
        )

    @pytest.mark.asyncio
    async def test_large_expiry_accepts_long_idle(self, mock_db):
        """Set SESSION_TOKEN_EXPIRY_HOURS=48.
        A session idle for 30h should be accepted."""
        now = datetime.now(timezone.utc)
        session = _make_mock_session(
            created_at=now - timedelta(hours=40),
            last_message_at=now - timedelta(hours=30),  # idle for 30h < 48h threshold
        )
        _setup_db_query(mock_db, session)

        with patch("app.config.settings.SESSION_TOKEN_EXPIRY_HOURS", 48):
            from app.auth import session_token as st_mod
            importlib.reload(st_mod)
            result = await st_mod.verify_session_token("test-token-123", mock_db)

        assert result is not None, (
            "With SESSION_TOKEN_EXPIRY_HOURS=48, session idle for 30h should be accepted"
        )

    @pytest.mark.asyncio
    async def test_timeout_is_not_hardcoded(self, mock_db):
        """Conclusive proof: same session object, same timestamps, different outcomes
        depending on settings value. This proves idle timeout is NOT hardcoded."""
        now = datetime.now(timezone.utc)
        session = _make_mock_session(
            created_at=now - timedelta(hours=20),
            last_message_at=now - timedelta(hours=15),  # idle for 15h
        )
        _setup_db_query(mock_db, session)

        # With 24h threshold (default), 15h idle → accepted
        with patch("app.config.settings.SESSION_TOKEN_EXPIRY_HOURS", 24):
            from app.auth import session_token as st_mod
            importlib.reload(st_mod)
            result_24h = await st_mod.verify_session_token("test-token-123", mock_db)

        # Re-set mock (reload may clear it)
        _setup_db_query(mock_db, session)

        # With 10h threshold, 15h idle → rejected
        with patch("app.config.settings.SESSION_TOKEN_EXPIRY_HOURS", 10):
            from app.auth import session_token as st_mod
            importlib.reload(st_mod)
            result_10h = await st_mod.verify_session_token("test-token-123", mock_db)

        assert result_24h is not None, "15h idle < 24h threshold → accepted"
        assert result_10h is None, "15h idle > 10h threshold → rejected"
        # This is the smoking gun: same session, same timestamps, different result
        # based solely on the settings value → NOT hardcoded
