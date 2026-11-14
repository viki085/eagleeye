"""Outbound email over SMTP with implicit TLS (e.g. Gmail with an app password).

Used for operator notifications only (demo sign-ins). Sending runs in a thread so the event
loop never blocks; failures are logged and never reach the user.
"""

import asyncio
import logging
import smtplib
import ssl
from email.message import EmailMessage

from eagleeye_core.config import Settings

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_S = 15


def email_configured(settings: Settings) -> bool:
    return bool(settings.smtp_username and settings.smtp_password)


def _send_blocking(settings: Settings, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = f"EagleEye <{settings.smtp_username}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(
        settings.smtp_host, settings.smtp_port, context=context, timeout=SMTP_TIMEOUT_S
    ) as smtp:
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


async def send_email(settings: Settings, to: str, subject: str, body: str) -> bool:
    """True when the message was handed to the SMTP server."""
    if not email_configured(settings):
        logger.warning("email to %s skipped: SMTP_USERNAME / SMTP_PASSWORD are not set", to)
        return False
    try:
        await asyncio.to_thread(_send_blocking, settings, to, subject, body)
    except (smtplib.SMTPException, OSError):
        logger.exception("email to %s failed", to)
        return False
    return True
