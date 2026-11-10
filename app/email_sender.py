"""Outgoing email, behind one function so the delivery method is swappable.

Providers (``LIFE_INBOX_EMAIL_PROVIDER``):
- ``console``: prints the email in the server terminal. Local development only.
- ``fake``: keeps emails in ``FAKE_OUTBOX`` for automated tests.
- ``smtp``: real delivery over SMTP (Gmail with an app password, or any
  provider). Configure ``LIFE_INBOX_SMTP_HOST``, ``..._PORT`` (587 STARTTLS
  by default; 465 uses SSL), ``..._USER``, ``..._PASSWORD`` and
  ``LIFE_INBOX_SMTP_FROM`` (``LIFE_INBOX_EMAIL_FROM`` also works).
- ``off``: no email at all. "Forgot password" says it isn't set up; the
  operator resets a password with ``python -m scripts.reset_password``.
  Allowed for a private beta, never in production.

Another provider (e.g. Resend) plugs in the same way without changing callers.
"""

from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from app.config import load_config


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    body: str


FAKE_OUTBOX: list[OutgoingEmail] = []


def _send_console(message: OutgoingEmail) -> None:
    border = "=" * 64
    print(
        f"\n{border}\n"
        "[Life Inbox email, console mode: not actually sent]\n"
        f"To:      {message.to}\n"
        f"Subject: {message.subject}\n\n"
        f"{message.body}\n"
        f"{border}\n",
        flush=True,
    )


def _send_fake(message: OutgoingEmail) -> None:
    FAKE_OUTBOX.append(message)


def _send_smtp(message: OutgoingEmail) -> None:
    host = os.getenv("LIFE_INBOX_SMTP_HOST", "").strip()
    port = int(os.getenv("LIFE_INBOX_SMTP_PORT", "587") or "587")
    user = os.getenv("LIFE_INBOX_SMTP_USER", "").strip()
    password = os.getenv("LIFE_INBOX_SMTP_PASSWORD", "")
    sender = (os.getenv("LIFE_INBOX_SMTP_FROM", "").strip()
              or os.getenv("LIFE_INBOX_EMAIL_FROM", "").strip() or user)
    if not host or not sender:
        raise RuntimeError("SMTP is not configured (host and from address needed).")

    email = EmailMessage()
    email["From"] = sender
    email["To"] = message.to
    email["Subject"] = message.subject
    email.set_content(message.body)

    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=15, context=context) as server:
            if user:
                server.login(user, password)
            server.send_message(email)
        return
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls(context=context)
        if user:
            server.login(user, password)
        server.send_message(email)


class EmailOff(RuntimeError):
    """Email is switched off on this Life Inbox (LIFE_INBOX_EMAIL_PROVIDER=off)."""


def _send_off(message: OutgoingEmail) -> None:
    raise EmailOff("Email isn't set up on this Life Inbox.")
_PROVIDERS = {
    "console": _send_console,
    "fake": _send_fake,
    "smtp": _send_smtp,
    "off": _send_off,
}


def send_email(to: str, subject: str, body: str) -> str:
    """Send an email; returns the provider name used."""
    provider = load_config(strict=False).email_provider
    sender = _PROVIDERS.get(provider)
    if sender is None:
        raise RuntimeError(f"Email provider {provider!r} is not available.")
    sender(OutgoingEmail(to=to, subject=subject, body=body))
    return provider


def current_provider() -> str:
    return load_config(strict=False).email_provider
