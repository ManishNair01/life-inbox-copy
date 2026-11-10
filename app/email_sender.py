"""Outgoing email, behind one function so the delivery method is swappable.

Providers (``LIFE_INBOX_EMAIL_PROVIDER``):
- ``console``: prints the email in the server terminal. Local development only.
- ``fake``: keeps emails in ``FAKE_OUTBOX`` for automated tests.
- ``smtp``: real email through an SMTP server (for example Gmail with an app
  password): ``LIFE_INBOX_SMTP_HOST``, ``LIFE_INBOX_SMTP_PORT`` (587, STARTTLS),
  ``LIFE_INBOX_SMTP_USER``, ``LIFE_INBOX_SMTP_PASSWORD``, ``LIFE_INBOX_EMAIL_FROM``.
- ``off``: no email at all. "Forgot password" says it isn't set up; the
  operator resets a password with ``python -m scripts.reset_password``.
  Allowed for a private beta, never in production.
"""

from __future__ import annotations

import os
import smtplib
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


def smtp_settings() -> dict:
    return {
        "host": os.getenv("LIFE_INBOX_SMTP_HOST", "").strip(),
        "port": int(os.getenv("LIFE_INBOX_SMTP_PORT", "587") or "587"),
        "user": os.getenv("LIFE_INBOX_SMTP_USER", "").strip(),
        "password": os.getenv("LIFE_INBOX_SMTP_PASSWORD", ""),
        "from": os.getenv("LIFE_INBOX_EMAIL_FROM", "").strip() or os.getenv("LIFE_INBOX_SMTP_USER", "").strip(),
    }


def _send_smtp(message: OutgoingEmail) -> None:
    settings = smtp_settings()
    email = EmailMessage()
    email["From"] = settings["from"]
    email["To"] = message.to
    email["Subject"] = message.subject
    email.set_content(message.body)
    with smtplib.SMTP(settings["host"], settings["port"], timeout=20) as server:
        server.starttls()
        if settings["user"]:
            server.login(settings["user"], settings["password"])
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
