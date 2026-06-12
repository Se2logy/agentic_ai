"""Secure, time-limited link generation and verification using HMAC-signed tokens."""

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LinkPayload:
    """Decoded token payload."""

    session_id: str
    purpose: str
    exp: int  # Unix timestamp
    return_url: str | None = None


class InvalidTokenError(Exception):
    """Raised when a link token is invalid or expired."""


class LinkService:
    """Generate and verify HMAC-signed, time-limited tokens for secure links.

    Token format::

        base64url(json_payload) + "." + hmac_signature

    The payload contains the session_id, purpose, and expiry timestamp.
    The HMAC signature is computed over the base64url-encoded payload
    using LINK_SECRET from application config.
    """

    def __init__(self) -> None:
        self.secret = settings.LINK_SECRET.encode()
        self.expiry_hours = settings.LINK_EXPIRY_HOURS

    # ── Public API ────────────────────────────────────────────────

    def generate_upload_link(
        self,
        session_id: str,
        purpose: str = "id_upload",
        return_url: str | None = None,
    ) -> str:
        """Generate a secure upload link token.

        Args:
            session_id: The check-in session this link belongs to.
            purpose: Link purpose identifier (default: "id_upload").
            return_url: Optional URL to redirect back to after upload.

        Returns:
            Token string (base64url(payload) + "." + hmac).
        """
        return self._create_token(session_id, purpose, return_url=return_url)

    def generate_incidental_link(
        self, session_id: str, return_url: str | None = None
    ) -> str:
        """Generate a secure incidental-protection link token.

        Args:
            session_id: The check-in session this link belongs to.
            return_url: Optional URL to redirect back to after selection.

        Returns:
            Token string.
        """
        return self._create_token(
            session_id, "incidental_protection", return_url=return_url
        )

    def verify_link(self, token: str) -> dict | None:
        """Verify a link token and return its payload, or None if invalid/expired.

        Args:
            token: The token string to verify.

        Returns:
            Dict with ``session_id``, ``purpose``, and optionally
            ``return_url`` if valid, else None.
        """
        try:
            return self._verify_token(token)
        except InvalidTokenError:
            logger.warning("Invalid or expired link token: %s...", token[:20])
            return None

    # ── Token internals ───────────────────────────────────────────

    def _create_token(
        self,
        session_id: str,
        purpose: str,
        return_url: str | None = None,
    ) -> str:
        exp = int(time.time()) + (self.expiry_hours * 3600)
        payload: dict = {"session_id": session_id, "purpose": purpose, "exp": exp}
        if return_url is not None:
            payload["return_url"] = return_url
        payload_json = json.dumps(payload, separators=(",", ":"))
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        signature = self._sign(payload_b64)
        return f"{payload_b64}.{signature}"

    def _verify_token(self, token: str) -> dict:
        """Verify and decode a token. Raises InvalidTokenError on failure."""
        parts = token.split(".")
        if len(parts) != 2:
            raise InvalidTokenError("Malformed token: expected two parts")

        payload_b64, signature = parts

        # Verify HMAC
        expected_sig = self._sign(payload_b64)
        if not hmac.compare_digest(signature, expected_sig):
            raise InvalidTokenError("Invalid HMAC signature")

        # Decode payload
        # Re-add padding that was stripped during encode
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64_padded = payload_b64 + "=" * padding
        else:
            payload_b64_padded = payload_b64

        try:
            payload_json = base64.urlsafe_b64decode(payload_b64_padded)
            payload = json.loads(payload_json)
        except (json.JSONDecodeError, Exception) as exc:
            raise InvalidTokenError(f"Failed to decode payload: {exc}")

        # Check expiry
        if payload.get("exp", 0) < time.time():
            raise InvalidTokenError("Token has expired")

        return {
            "session_id": payload["session_id"],
            "purpose": payload["purpose"],
            "return_url": payload.get("return_url"),
        }

    def _sign(self, payload_b64: str) -> str:
        """Compute HMAC-SHA256 signature over the base64url payload."""
        mac = hmac.new(self.secret, payload_b64.encode(), hashlib.sha256)
        return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


# Singleton instance
link_service = LinkService()
