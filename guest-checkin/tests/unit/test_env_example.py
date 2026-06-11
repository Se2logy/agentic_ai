"""Tests for .env.example — key coverage and credential safety.

Covers:
- All keys in .env.example are recognized by Settings class
- No real credentials (passwords/tokens) are present in .env.example
"""

import re
from pathlib import Path

import pytest

from app.config import Settings

_ENV_EXAMPLE = Path(__file__).resolve().parent.parent.parent / ".env.example"


@pytest.fixture
def env_lines():
    """Load .env.example as non-comment, non-empty lines."""
    text = _ENV_EXAMPLE.read_text()
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        # Skip comments and blank lines
        if not stripped or stripped.startswith("#"):
            continue
        lines.append(stripped)
    return lines


class TestEnvExampleCoverage:
    """Every key in .env.example should be a recognized Settings field."""

    def test_all_env_keys_in_settings(self, env_lines):
        """Extract KEY= keys from .env.example and verify they exist in Settings.model_fields."""
        model_fields = set(Settings.model_fields.keys())
        missing = []
        for line in env_lines:
            key = line.split("=", 1)[0].strip()
            if key and key not in model_fields:
                missing.append(key)
        assert not missing, (
            f"Keys in .env.example not found in Settings.model_fields: {missing}"
        )

    def test_env_example_file_exists(self):
        """The .env.example file should exist."""
        assert _ENV_EXAMPLE.is_file(), f".env.example not found at {_ENV_EXAMPLE}"


class TestEnvExampleNoRealCredentials:
    """No .env.example value should look like a real password or token."""

    # Patterns that look like real credentials (not placeholders)
    _REAL_SECRET_PATTERNS = [
        re.compile(r"(?:password|passwd|secret|token|api.key)\s*=\s*[A-Za-z0-9_\-]{16,}", re.IGNORECASE),
        re.compile(r"(?:password|passwd|secret|token|api.key)\s*=\s*sk-[a-zA-Z0-9]+", re.IGNORECASE),
    ]

    # Values that are clearly placeholders and should be allowed
    _ALLOWLIST = {
        "change-me-in-production",
        "your-secret-here",
        "guestcheckin",  # default dev DB credentials (not production)
        "localhost",
        "",
    }

    def test_no_real_secrets(self, env_lines):
        """Values in .env.example should not look like real secrets."""
        for line in env_lines:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()

            # Skip if the value is a known placeholder
            if value.lower() in self._ALLOWLIST:
                continue

            # Skip numeric-only values (ports, hours)
            if value.isdigit():
                continue

            # Skip URL-like values (DATABASE_URL, OLLAMA_BASE_URL, etc.)
            if value.startswith(("http://", "https://", "mysql://", "mysql+")):
                continue

            # Skip JSON-like values (CORS_ORIGINS)
            if value.startswith("["):
                continue

            # Skip path-like values
            if value.startswith("/"):
                continue

            # Skip header name values (X-API-Key)
            if value.startswith("X-"):
                continue

            # For SMTP_PASS specifically, check it's a placeholder
            if key.upper() == "SMTP_PASS":
                assert value in self._ALLOWLIST or len(value) < 12, (
                    f"SMTP_PASS value looks like a real credential: {value!r}"
                )

            # Generic check: no long random-looking strings as secret values
            for pattern in self._REAL_SECRET_PATTERNS:
                assert not pattern.search(f"{key}={value}"), (
                    f"Potential real credential found in .env.example: {key}={value!r}"
                )
