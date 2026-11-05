"""Task editing, surfaced server errors and the SMTP email provider."""

import smtplib
from types import SimpleNamespace

import pytest

from tests.auth_helpers import register
from tests.test_calendar import client  # noqa: F401  (shared fixture)


def _make_task(client, **overrides):  # noqa: F811
    payload = {"text": "Original task", "priority": "Medium", "due_on": "2030-03-12"}
    payload.update(overrides)
    response = client.post("/api/tasks", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _events(client, month="2030-03"):  # noqa: F811
    return client.get(
        f"/api/calendar/events?start={month}-01&end={month}-31"
    ).json()


# --- edit tasks ---------------------------------------------------------------


def test_edit_text_priority_and_date_moves_the_calendar_event(client):  # noqa: F811
    task = _make_task(client)
    assert [e["event_date"] for e in _events(client)] == ["2030-03-12"]

    response = client.patch(
        f"/api/tasks/{task['id']}",
        json={"text": "Renamed task", "priority": "High", "due_on": "2030-03-20"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["text"] == "Renamed task"
    assert body["priority"] == "High"
    assert body["due_on"] == "2030-03-20"
    assert body["timing_confirmed"] is True
    events = _events(client)
    assert [e["event_date"] for e in events] == ["2030-03-20"]
    assert events[0]["title"] == "Renamed task"


def test_clear_due_date_removes_the_calendar_event(client):  # noqa: F811
    task = _make_task(client)
    response = client.patch(
        f"/api/tasks/{task['id']}", json={"clear_due_date": True}
    )
    assert response.status_code == 200
    assert response.json()["due_on"] is None
    assert _events(client) == []


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": ""},
        {"priority": "Urgent"},
        {"due_on": "2030-03-20", "clear_due_date": True},
        {"surprise": 1},
    ],
)
def test_edit_task_rejects_bad_input(client, payload):  # noqa: F811
    task = _make_task(client)
    assert client.patch(f"/api/tasks/{task['id']}", json=payload).status_code == 422


def test_cannot_edit_another_users_task(client):  # noqa: F811
    task = _make_task(client)
    client.post("/api/auth/logout")
    register(client, "intruder@example.com")
    response = client.patch(f"/api/tasks/{task['id']}", json={"text": "hijacked"})
    assert response.status_code == 404
    assert client.patch("/api/tasks/99999", json={"text": "x"}).status_code == 404


def test_reanalysis_does_not_overwrite_a_users_edit(client):  # noqa: F811
    client.post("/api/items", json={"raw_text": "Call the bank on Monday morning"})
    assert client.post("/api/analyze").status_code == 200
    task = client.get("/api/tasks").json()[0]

    edited = client.patch(
        f"/api/tasks/{task['id']}",
        json={"text": "Phone the credit union", "priority": "High"},
    ).json()
    assert edited["text"] == "Phone the credit union"

    assert client.post("/api/analyze").status_code == 200
    again = [t for t in client.get("/api/tasks").json() if t["id"] == task["id"]][0]
    assert again["text"] == "Phone the credit union"
    assert again["priority"] == "High"


def test_ui_has_edit_button_and_shows_server_messages(client):  # noqa: F811
    source = client.get("/static/app.js").text
    assert "function showEditTask(" in source
    assert "actionButton('Edit'" in source
    assert "typeof body.detail === 'string'" in source


# --- SMTP email provider --------------------------------------------------------


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.steps = []
        self.sent = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.steps.append("starttls")

    def login(self, user, password):
        self.steps.append(("login", user, password))

    def send_message(self, message):
        self.sent = message


@pytest.fixture()
def smtp_env(monkeypatch):
    _FakeSMTP.instances = []
    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("LIFE_INBOX_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("LIFE_INBOX_SMTP_USER", "me@example.com")
    monkeypatch.setenv("LIFE_INBOX_SMTP_PASSWORD", "app-password")
    monkeypatch.delenv("LIFE_INBOX_SMTP_FROM", raising=False)
    monkeypatch.delenv("LIFE_INBOX_SMTP_PORT", raising=False)
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _FakeSMTP)


def test_smtp_sends_with_starttls_and_login(smtp_env):
    from app import email_sender

    assert email_sender.send_email("you@example.com", "Hello", "Body text") == "smtp"
    server = _FakeSMTP.instances[0]
    assert (server.host, server.port) == ("smtp.example.com", 587)
    assert server.steps == ["starttls", ("login", "me@example.com", "app-password")]
    assert server.sent["To"] == "you@example.com"
    assert server.sent["From"] == "me@example.com"
    assert server.sent["Subject"] == "Hello"
    assert "Body text" in server.sent.get_content()


def test_smtp_port_465_uses_ssl_without_starttls(smtp_env, monkeypatch):
    from app import email_sender

    monkeypatch.setenv("LIFE_INBOX_SMTP_PORT", "465")
    email_sender.send_email("you@example.com", "Hi", "Body")
    assert _FakeSMTP.instances[0].steps == [("login", "me@example.com", "app-password")]


def test_smtp_requires_configuration(monkeypatch):
    from app import email_sender

    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "smtp")
    monkeypatch.delenv("LIFE_INBOX_SMTP_HOST", raising=False)
    with pytest.raises(RuntimeError, match="SMTP is not configured"):
        email_sender.send_email("you@example.com", "Hi", "Body")


def test_smtp_provider_must_be_configured_in_strict_mode(monkeypatch):
    from app.config import ConfigError, load_config

    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "smtp")
    monkeypatch.delenv("LIFE_INBOX_SMTP_HOST", raising=False)
    with pytest.raises(ConfigError, match="SMTP_HOST"):
        load_config(strict=True)


def test_forgot_password_still_succeeds_when_mail_fails(client, monkeypatch):  # noqa: F811
    register(client, "mailfail@example.com")
    client.post("/api/auth/logout")
    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("LIFE_INBOX_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("LIFE_INBOX_SMTP_USER", "me@example.com")

    def boom(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    known = client.post("/api/auth/password/forgot", json={"email": "mailfail@example.com"})
    unknown = client.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json()
