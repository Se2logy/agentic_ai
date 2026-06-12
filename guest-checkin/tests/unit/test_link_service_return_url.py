"""Unit tests for link_service return_url feature (Bug 1)."""

import base64
import hashlib
import hmac
import json
import time

import pytest

from app.services.link_service import LinkService


class TestReturnUrlInToken:
    """Verify return_url is embedded in link tokens and returned on verify."""

    def test_generate_upload_link_with_return_url(self):
        svc = LinkService()
        token = svc.generate_upload_link(
            "session-abc", return_url="https://host/chat?session=abc"
        )
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["session_id"] == "session-abc"
        assert payload["purpose"] == "id_upload"
        assert payload["return_url"] == "https://host/chat?session=abc"

    def test_generate_upload_link_without_return_url(self):
        svc = LinkService()
        token = svc.generate_upload_link("session-abc")
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["return_url"] is None

    def test_generate_incidental_link_with_return_url(self):
        svc = LinkService()
        token = svc.generate_incidental_link(
            "session-def", return_url="https://host/chat?session=def"
        )
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["session_id"] == "session-def"
        assert payload["purpose"] == "incidental_protection"
        assert payload["return_url"] == "https://host/chat?session=def"

    def test_generate_incidental_link_without_return_url(self):
        svc = LinkService()
        token = svc.generate_incidental_link("session-def")
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["return_url"] is None

    def test_return_url_in_raw_payload(self):
        """Verify return_url is present in the decoded JSON payload."""
        svc = LinkService()
        token = svc.generate_upload_link(
            "s1", return_url="https://example.com/back"
        )
        # Decode the payload part directly
        payload_b64 = token.split(".")[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        assert payload["return_url"] == "https://example.com/back"
        assert payload["session_id"] == "s1"

    def test_no_return_url_key_in_payload_when_absent(self):
        """Verify return_url key is absent from payload when not provided."""
        svc = LinkService()
        token = svc.generate_upload_link("s1")
        payload_b64 = token.split(".")[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        assert "return_url" not in payload

    def test_backward_compat_old_token_still_verifies(self):
        """Tokens generated without return_url (old format) still verify."""
        svc = LinkService()
        # Craft a token the old way (no return_url field)
        exp = int(time.time()) + 3600
        payload = {"session_id": "s-old", "purpose": "id_upload", "exp": exp}
        payload_json = json.dumps(payload, separators=(",", ":"))
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        mac = hmac.new(svc.secret, payload_b64.encode(), hashlib.sha256)
        sig = base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")
        token = f"{payload_b64}.{sig}"

        result = svc.verify_link(token)
        assert result is not None
        assert result["session_id"] == "s-old"
        assert result["purpose"] == "id_upload"
        assert result["return_url"] is None

    def test_return_url_with_special_chars(self):
        """Verify return_url with query params and special chars roundtrips."""
        svc = LinkService()
        url = "https://host/chat?session=abc&token=xyz#section"
        token = svc.generate_upload_link("s1", return_url=url)
        payload = svc.verify_link(token)
        assert payload["return_url"] == url

    def test_custom_purpose_with_return_url(self):
        """Verify custom purpose + return_url work together."""
        svc = LinkService()
        token = svc.generate_upload_link(
            "s1", purpose="custom", return_url="https://host/return"
        )
        payload = svc.verify_link(token)
        assert payload["purpose"] == "custom"
        assert payload["return_url"] == "https://host/return"

    def test_tampered_return_url_invalidates_token(self):
        """Changing the return_url in a token invalidates the HMAC."""
        svc = LinkService()
        token = svc.generate_upload_link(
            "s1", return_url="https://good.url/chat"
        )
        # Decode, change return_url, re-encode with same signature (should fail)
        parts = token.split(".")
        payload_b64 = parts[0]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        payload["return_url"] = "https://evil.url/phishing"
        new_payload_json = json.dumps(payload, separators=(",", ":"))
        new_payload_b64 = base64.urlsafe_b64encode(
            new_payload_json.encode()
        ).decode().rstrip("=")
        tampered_token = f"{new_payload_b64}.{parts[1]}"
        result = svc.verify_link(tampered_token)
        assert result is None
