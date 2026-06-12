"""Unit tests for link_service return_url feature (Bug 1).

Covers:
- return_url round-trip through generate + verify
- Backward compatibility (no return_url)
- Expired token detection
- Incidental link return_url
- HMAC tamper detection
"""

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.services.link_service import InvalidTokenError, LinkService


class TestReturnUrl:
    """Verify return_url is embedded in link tokens and returned on verify."""

    def test_generate_upload_link_includes_return_url(self):
        """generate_upload_link with return_url embeds it; verify_link returns it."""
        svc = LinkService()
        token = svc.generate_upload_link(
            session_id="test-session",
            return_url="https://example.com/chat?session=abc",
        )
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["return_url"] == "https://example.com/chat?session=abc"

    def test_verify_link_returns_return_url(self):
        """Round-trip encoding/decoding preserves return_url exactly."""
        svc = LinkService()
        url = "https://example.com/chat?session=abc&foo=bar#frag"
        token = svc.generate_upload_link(session_id="test-session", return_url=url)
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["return_url"] == url

    def test_generate_link_without_return_url(self):
        """Backward compat: omitting return_url yields None on verify."""
        svc = LinkService()
        token = svc.generate_upload_link(
            session_id="test-session", return_url=None
        )
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["return_url"] is None

    def test_expired_link_still_fails(self):
        """An expired token with return_url raises InvalidTokenError."""
        svc = LinkService()
        # Manually craft a token with a past expiry
        payload_data = {
            "session_id": "test-session",
            "purpose": "id_upload",
            "exp": int(time.time()) - 3600,  # expired 1 hour ago
            "return_url": "https://example.com/chat?session=abc",
        }
        payload_json = json.dumps(payload_data, separators=(",", ":"))
        payload_b64 = (
            base64.urlsafe_b64encode(payload_json.encode())
            .decode()
            .rstrip("=")
        )
        mac = hmac.new(svc.secret, payload_b64.encode(), hashlib.sha256)
        sig = base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")
        token = f"{payload_b64}.{sig}"

        with pytest.raises(InvalidTokenError):
            svc._verify_token(token)

    def test_generate_incidental_link_includes_return_url(self):
        """generate_incidental_link with return_url embeds it; verify returns it."""
        svc = LinkService()
        token = svc.generate_incidental_link(
            session_id="test-session",
            return_url="https://example.com/chat?session=abc",
        )
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["purpose"] == "incidental_protection"
        assert payload["return_url"] == "https://example.com/chat?session=abc"

    def test_return_url_tamper_detection(self):
        """Modifying return_url in the token invalidates HMAC on verify."""
        svc = LinkService()
        token = svc.generate_upload_link(
            session_id="test-session",
            return_url="https://good.url/chat",
        )
        # Decode payload, tamper return_url, re-encode with original signature
        parts = token.split(".")
        payload_b64 = parts[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        payload["return_url"] = "https://evil.url/phishing"
        new_payload_json = json.dumps(payload, separators=(",", ":"))
        new_payload_b64 = (
            base64.urlsafe_b64encode(new_payload_json.encode())
            .decode()
            .rstrip("=")
        )
        tampered_token = f"{new_payload_b64}.{parts[1]}"

        with pytest.raises(InvalidTokenError):
            svc._verify_token(tampered_token)
