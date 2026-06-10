"""Unit tests for services — email, payment, storage, links."""

import asyncio
import base64
import json
import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Email Service ─────────────────────────────────────────────────


class TestEmailService:
    """Tests for EmailService."""

    def test_init_reads_settings(self):
        from app.services.email_service import EmailService

        svc = EmailService()
        assert svc.host == "mailhog"
        assert svc.port == 1025
        assert svc.from_addr == "checkin@guestapp.local"

    @pytest.mark.asyncio
    async def test_send_otp_email_success(self, tmp_path):
        from app.services.email_service import EmailService

        svc = EmailService()
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await svc.send_otp_email(
                to_email="guest@example.com",
                otp_code="123456",
                guest_name="Jane Doe",
            )
        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        msg = call_args[0][0]
        assert msg["To"] == "guest@example.com"
        assert msg["Subject"] == "Your Check-In Verification Code"
        # Body should contain the OTP code
        body = str(msg.get_content())
        assert "123456" in body

    @pytest.mark.asyncio
    async def test_send_otp_email_smtp_failure(self):
        from app.services.email_service import EmailService
        import aiosmtplib

        svc = EmailService()
        with patch(
            "aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=aiosmtplib.SMTPException("connection refused"),
        ):
            result = await svc.send_otp_email(
                to_email="guest@example.com",
                otp_code="654321",
                guest_name="John",
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_send_notification_success(self):
        from app.services.email_service import EmailService

        svc = EmailService()
        with patch("aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            result = await svc.send_notification(
                to_email="guest@example.com",
                subject="Welcome",
                body="Welcome to your stay!",
            )
        assert result is True
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert msg["Subject"] == "Welcome"

    @pytest.mark.asyncio
    async def test_send_notification_failure(self):
        from app.services.email_service import EmailService
        import aiosmtplib

        svc = EmailService()
        with patch(
            "aiosmtplib.send",
            new_callable=AsyncMock,
            side_effect=Exception("SMTP down"),
        ):
            result = await svc.send_notification(
                to_email="guest@example.com",
                subject="Test",
                body="Body",
            )
        assert result is False


# ── Payment Service ──────────────────────────────────────────────


class TestPaymentService:
    """Tests for PaymentGateway ABC and MockPayment."""

    def test_payment_result_dataclass(self):
        from app.services.payment_service import PaymentResult

        r = PaymentResult(success=True, transaction_id="tx-1", message="ok")
        assert r.success is True
        assert r.transaction_id == "tx-1"
        assert r.message == "ok"

    def test_payment_gateway_is_abstract(self):
        from app.services.payment_service import PaymentGateway

        with pytest.raises(TypeError):
            PaymentGateway()

    @pytest.mark.asyncio
    async def test_mock_process_payment(self):
        from app.services.payment_service import MockPayment

        gw = MockPayment()
        result = await gw.process_payment(
            guest_id="g1",
            amount=99.99,
            description="Damage Waiver",
            metadata={"session_id": "s1"},
        )
        assert result.success is True
        assert result.transaction_id.startswith("mock-")
        assert "99.99" in result.message

    @pytest.mark.asyncio
    async def test_mock_refund(self):
        from app.services.payment_service import MockPayment

        gw = MockPayment()
        result = await gw.refund("mock-abc123")
        assert result.success is True
        assert result.transaction_id.startswith("mock-refund-")
        assert "mock-abc123" in result.message

    @pytest.mark.asyncio
    async def test_mock_payment_unique_txn_ids(self):
        from app.services.payment_service import MockPayment

        gw = MockPayment()
        r1 = await gw.process_payment("g1", 10.0, "test")
        r2 = await gw.process_payment("g1", 10.0, "test")
        assert r1.transaction_id != r2.transaction_id


# ── Storage Service ──────────────────────────────────────────────


class TestStorageService:
    """Tests for StorageService."""

    @pytest.mark.asyncio
    async def test_save_file_success(self, tmp_path):
        from app.services.storage_service import StorageService

        svc = StorageService()
        svc.upload_dir = tmp_path

        data = b"fake-image-data"
        path = await svc.save_file(data, "photo.jpg", "ids")
        assert os.path.exists(path)
        assert "ids" in path
        assert path.endswith("photo.jpg")

        # Read back
        read_data = await svc.get_file(path)
        assert read_data == data

    @pytest.mark.asyncio
    async def test_save_file_creates_subfolder(self, tmp_path):
        from app.services.storage_service import StorageService

        svc = StorageService()
        svc.upload_dir = tmp_path

        path = await svc.save_file(b"data", "doc.pdf", "custom_sub")
        assert os.path.exists(path)
        assert "custom_sub" in path

    @pytest.mark.asyncio
    async def test_save_file_rejects_large_file(self, tmp_path):
        from app.services.storage_service import StorageService, FileTooLargeError

        svc = StorageService()
        svc.upload_dir = tmp_path

        big_data = b"x" * (10 * 1024 * 1024 + 1)  # 10 MB + 1 byte
        with pytest.raises(FileTooLargeError):
            await svc.save_file(big_data, "big.jpg", "ids")

    @pytest.mark.asyncio
    async def test_save_file_rejects_invalid_extension(self, tmp_path):
        from app.services.storage_service import StorageService, InvalidExtensionError

        svc = StorageService()
        svc.upload_dir = tmp_path

        with pytest.raises(InvalidExtensionError):
            await svc.save_file(b"data", "malware.exe", "ids")

    @pytest.mark.asyncio
    async def test_save_file_allows_valid_extensions(self, tmp_path):
        from app.services.storage_service import StorageService

        svc = StorageService()
        svc.upload_dir = tmp_path

        for ext in [".jpg", ".jpeg", ".png", ".pdf"]:
            path = await svc.save_file(b"data", f"file{ext}", "ids")
            assert os.path.exists(path)

    @pytest.mark.asyncio
    async def test_get_file_not_found(self, tmp_path):
        from app.services.storage_service import StorageService

        svc = StorageService()
        svc.upload_dir = tmp_path

        with pytest.raises(FileNotFoundError):
            await svc.get_file(str(tmp_path / "nonexistent.jpg"))


# ── Link Service ─────────────────────────────────────────────────


class TestLinkService:
    """Tests for LinkService."""

    def test_generate_upload_link_returns_token(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        token = svc.generate_upload_link("session-123")
        assert isinstance(token, str)
        assert "." in token  # payload.signature format

    def test_generate_incidental_link_returns_token(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        token = svc.generate_incidental_link("session-456")
        assert isinstance(token, str)
        assert "." in token

    def test_verify_valid_upload_link(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        token = svc.generate_upload_link("session-abc")
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["session_id"] == "session-abc"
        assert payload["purpose"] == "id_upload"

    def test_verify_valid_incidental_link(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        token = svc.generate_incidental_link("session-def")
        payload = svc.verify_link(token)
        assert payload is not None
        assert payload["session_id"] == "session-def"
        assert payload["purpose"] == "incidental_protection"

    def test_verify_expired_link_returns_none(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        # Manually craft an expired token
        payload = {
            "session_id": "session-exp",
            "purpose": "id_upload",
            "exp": int(time.time()) - 3600,  # expired 1 hour ago
        }
        payload_json = json.dumps(payload, separators=(",", ":"))
        payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
        import hashlib
        import hmac

        mac = hmac.new(svc.secret, payload_b64.encode(), hashlib.sha256)
        sig = base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")
        token = f"{payload_b64}.{sig}"

        result = svc.verify_link(token)
        assert result is None

    def test_verify_tampered_link_returns_none(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        token = svc.generate_upload_link("session-tamper")
        # Tamper with the token
        parts = token.split(".")
        tampered = parts[0] + "X." + parts[1]
        result = svc.verify_link(tampered)
        assert result is None

    def test_verify_malformed_link_returns_none(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        result = svc.verify_link("not-a-valid-token")
        assert result is None

    def test_verify_random_token_returns_none(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        result = svc.verify_link("abc.def")
        assert result is None

    def test_different_sessions_produce_different_tokens(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        t1 = svc.generate_upload_link("session-1")
        t2 = svc.generate_upload_link("session-2")
        assert t1 != t2

    def test_custom_purpose_in_upload_link(self):
        from app.services.link_service import LinkService

        svc = LinkService()
        token = svc.generate_upload_link("s1", purpose="custom_purpose")
        payload = svc.verify_link(token)
        assert payload["purpose"] == "custom_purpose"
