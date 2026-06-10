"""Async email service using aiosmtplib with Jinja2 template rendering."""

import logging
from pathlib import Path

import aiosmtplib
from email.message import EmailMessage
from jinja2 import Environment, FileSystemLoader

from app.config import settings

logger = logging.getLogger(__name__)

# Template directory — app/templates/
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=True,
)


class EmailService:
    """Sends emails via SMTP (async). In dev mode (SMTP_HOST=mailhog)
    it connects to MailHog on port 1025 with no auth."""

    def __init__(self) -> None:
        self.host = settings.SMTP_HOST
        self.port = settings.SMTP_PORT
        self.user = settings.SMTP_USER
        self.password = settings.SMTP_PASS
        self.from_addr = settings.SMTP_FROM

    # ── Public API ────────────────────────────────────────────────

    async def send_otp_email(
        self, to_email: str, otp_code: str, guest_name: str
    ) -> bool:
        """Render the OTP email template and send it.

        Returns True on success, False on failure.
        """
        try:
            template = _jinja_env.get_template("otp_email.html")
            html_body = template.render(
                guest_name=guest_name,
                otp_code=otp_code,
                expiry_minutes=10,
            )
            return await self._send(
                to=to_email,
                subject="Your Check-In Verification Code",
                html_body=html_body,
            )
        except Exception:
            logger.exception("Failed to send OTP email to %s", to_email)
            return False

    async def send_notification(
        self, to_email: str, subject: str, body: str
    ) -> bool:
        """Send a generic notification email (plain-text body).

        Returns True on success, False on failure.
        """
        try:
            return await self._send(
                to=to_email,
                subject=subject,
                text_body=body,
            )
        except Exception:
            logger.exception("Failed to send notification to %s", to_email)
            return False

    # ── Internal ──────────────────────────────────────────────────

    async def _send(
        self,
        to: str,
        subject: str,
        html_body: str | None = None,
        text_body: str | None = None,
    ) -> bool:
        """Low-level send via aiosmtplib. Returns True on success."""
        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject

        if html_body and text_body:
            msg.set_content(text_body)
            msg.add_alternative(html_body, subtype="html")
        elif html_body:
            msg.set_content(html_body, subtype="html")
        elif text_body:
            msg.set_content(text_body)
        else:
            msg.set_content("")

        use_tls = self.port == 465

        await aiosmtplib.send(
            msg,
            hostname=self.host,
            port=self.port,
            username=self.user or None,
            password=self.password or None,
            start_tls=not use_tls and bool(self.user),
            use_tls=use_tls,
        )
        logger.info("Email sent to %s: %s", to, subject)
        return True


# Singleton instance
email_service = EmailService()
