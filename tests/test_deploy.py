"""Deploying in a container: email for a deployed server (smtp, or off for a
private beta), the image and compose files, and copying a SQLite database into
a fresh one (Postgres in real use; SQLite here, so tests need no server)."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def beta_env(monkeypatch):
    monkeypatch.setenv("LIFE_INBOX_ENV", "beta")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db:5432/lifeinbox")
    monkeypatch.setenv("LIFE_INBOX_OTP_PEPPER", "x" * 40)
    for name in ("LIFE_INBOX_SMTP_HOST", "LIFE_INBOX_SMTP_USER", "LIFE_INBOX_SMTP_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_a_deployed_server_needs_real_email_or_off(beta_env, monkeypatch):
    from app.config import ConfigError, config_warnings, load_config

    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "console")
    with pytest.raises(ConfigError, match="smtp"):
        load_config()
    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "off")
    config = load_config()
    assert any("Forgot password" in warning for warning in config_warnings(config))
    monkeypatch.setenv("LIFE_INBOX_ENV", "production")
    with pytest.raises(ConfigError, match="private beta"):
        load_config()


def test_smtp_needs_its_settings_and_sends_with_starttls(beta_env, monkeypatch):
    from app import email_sender
    from app.config import ConfigError, load_config

    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "smtp")
    with pytest.raises(ConfigError, match="LIFE_INBOX_SMTP_HOST"):
        load_config()
    monkeypatch.setenv("LIFE_INBOX_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("LIFE_INBOX_SMTP_USER", "me@example.com")
    monkeypatch.setenv("LIFE_INBOX_SMTP_PASSWORD", "app-password-for-tests")
    load_config()

    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self, context=None):
            calls.append(("starttls",))

        def login(self, user, password):
            calls.append(("login", user))

        def send_message(self, message):
            calls.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr(email_sender.smtplib, "SMTP", FakeSMTP)
    assert email_sender.send_email("you@example.com", "Your code", "123456") == "smtp"
    assert calls == [("connect", "smtp.example.com", 587), ("starttls",), ("login", "me@example.com"),
                     ("send", "you@example.com", "Your code")]


def test_with_email_off_forgot_password_says_so(tmp_path, monkeypatch):
    import importlib

    from fastapi.testclient import TestClient

    modules = ("app.main", "app.database", "app.auth", "app.config", "app.organizer", "app.email_sender")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'off.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "off")
    for name in modules:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    try:
        with TestClient(main.app) as client:
            response = client.post("/api/auth/password/forgot", json={"email": "you@example.com"})
            assert response.status_code == 503
            assert "isn't set up" in response.json()["detail"]
    finally:
        importlib.import_module("app.database").engine.dispose()
        for name in modules:
            sys.modules.pop(name, None)


def test_the_image_and_compose_files_are_ready():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "tesseract-ocr" in dockerfile and "ffmpeg" in dockerfile
    assert "${PORT:-8000}" in dockerfile and "--proxy-headers" in dockerfile
    assert "alembic upgrade head" in dockerfile
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert {".env", "data/", ".venv/"} <= set(ignored)  # no secrets or personal data in the image
    vps = (ROOT / "docker-compose.vps.yml").read_text(encoding="utf-8")
    for needed in ("caddy", "scheduler", "POSTGRES_PASSWORD:?", "uploads:/data/uploads", "deploy/Caddyfile"):
        assert needed in vps, needed
    local = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    scheduler = local.split("  notifications:", 1)[1]
    assert "NVIDIA_API_KEY" in scheduler and "Asia/Kolkata" in scheduler
    example = (ROOT / "deploy/env.example").read_text(encoding="utf-8")
    assert "nvapi-" not in example and "LIFE_INBOX_OTP_PEPPER=\n" in example


def _migrated(path: Path) -> str:
    url = "sqlite:///" + str(path).replace("\\", "/")
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True, capture_output=True,
                   env={**os.environ, "DATABASE_URL": url})
    return url


def test_copying_a_database_into_a_fresh_one(tmp_path):
    import sqlite3

    from scripts.copy_sqlite_to_postgres import copy

    source = _migrated(tmp_path / "old.db")
    target = _migrated(tmp_path / "new.db")
    with sqlite3.connect(tmp_path / "old.db") as db:
        db.execute("INSERT INTO users (id, email, display_name, auth_provider, created_at) "
                   "VALUES (77, 'me@example.com', 'Me', 'password', '2026-11-01')")
        db.execute("INSERT INTO inbox_items (id, item_type, raw_text, processing_status, owner_user_id, created_at) "
                   "VALUES (5, 'text', 'Pay rent by 5th', 'ready', 77, '2026-11-01')")
        db.execute("INSERT INTO auth_sessions (user_id, token_hash, auth_method, created_at, last_seen_at, "
                   "idle_expires_at, absolute_expires_at) VALUES (77, 'h', 'password', 'x', 'x', 'x', 'x')")
        db.commit()
    lines = []
    counts = copy(source, target, dry_run=True, out=lines.append)
    assert counts["inbox_items"] == 1 and lines[-1].startswith("Dry run")
    copy(source, target, out=lines.append)
    with sqlite3.connect(tmp_path / "new.db") as db:
        assert db.execute("SELECT raw_text, owner_user_id FROM inbox_items").fetchall() == [("Pay rent by 5th", 77)]
        assert db.execute("SELECT email FROM users WHERE id = 77").fetchone() == ("me@example.com",)
        assert db.execute("SELECT COUNT(*) FROM auth_sessions").fetchone() == (0,)  # sign in again
    with pytest.raises(SystemExit, match="already has"):
        copy(source, target, out=lines.append)  # never into a database that has data


def test_sharing_over_a_tunnel_can_make_cookies_https_only(monkeypatch):
    # Sharing your own PC's Life Inbox through Tailscale Funnel (local mode).
    from app import auth

    monkeypatch.setenv("LIFE_INBOX_ENV", "local")
    monkeypatch.delenv("LIFE_INBOX_SECURE_COOKIES", raising=False)
    assert auth._secure_cookies() is False
    monkeypatch.setenv("LIFE_INBOX_SECURE_COOKIES", "1")
    assert auth._secure_cookies() is True
