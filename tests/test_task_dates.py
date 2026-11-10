"""Change 012 (part 1): you can always change a task's date (even a confirmed
one), the note keeps a history of its dates, and editing a note re-reads a
confirmed date and asks you to confirm the new one."""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'dates.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    # Never fetch the real internet in tests.
    monkeypatch.setattr(main, "fetch_url", lambda url: {
        "final_url": url,
        "title": "Statistics revision guide",
        "raw_text": "Hypothesis tests, confidence intervals and p-values.",
        "mime_type": "text/html",
        "status_code": 200,
    })
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com")
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def day(phrase):
    """What the date reader makes of a phrase today, so the tests never age."""
    from app.attention.dates import parse_timing_phrase

    return parse_timing_phrase(phrase).normalized_iso


def short(iso):
    from datetime import date

    value = date.fromisoformat(iso)
    return f"{value.strftime('%a')} {value.day} {value.strftime('%b')}"


def save_and_file(client, text):
    note = client.post("/api/items", json={"raw_text": text}).json()
    assert client.post("/api/analyze", params={"item_id": note["id"]}).status_code == 200
    return note


def edit_and_file(client, note, text):
    assert client.put(f"/api/items/{note['id']}", json={"raw_text": text}).status_code == 200
    assert client.post("/api/analyze", params={"item_id": note["id"]}).status_code == 200


def task_of(client, note):
    tasks = [t for t in client.get("/api/tasks", params={"status": "all"}).json() if note["id"] in t["source_item_ids"]]
    assert len(tasks) == 1, tasks
    return tasks[0]


def confirm(client, task):
    assert client.post(f"/api/tasks/{task['id']}/confirm-timing", json={}).status_code == 200


def updates(client, note):
    response = client.get(f"/api/items/{note['id']}/updates")
    assert response.status_code == 200, response.text
    return response.json()


# --- you can always change a date ------------------------------------------------------


def test_you_can_change_a_confirmed_date(client):
    note = save_and_file(client, "Attend Statistics meeting on 20 Nov")
    task = task_of(client, note)
    assert task["due_on"] == day("on 20 Nov")
    confirm(client, task)

    later = client.post(f"/api/tasks/{task['id']}/date", json={"due_on": day("on 26 Nov"), "due_time": "15:30"})
    assert later.status_code == 200, later.text
    body = later.json()
    assert body["due_on"] == day("on 26 Nov") and body["due_time"] == "15:30" and body["timing_confirmed"]

    earlier = client.post(f"/api/tasks/{task['id']}/date", json={"due_on": day("on 24 Nov")}).json()
    assert earlier["due_on"] == day("on 24 Nov") and earlier["due_time"] is None

    # The calendar follows.
    events = client.get("/api/calendar/events", params={"start": day("on 20 Nov"), "end": day("on 30 Nov")}).json()
    assert [e["event_date"] for e in events if e["source_item_id"] == note["id"]] == [day("on 24 Nov")]

    texts = [u["text"] for u in updates(client, note)]
    assert texts == [
        f"Moved earlier, from {short(day('on 26 Nov'))} at 15:30 to {short(day('on 24 Nov'))}",
        f"Postponed from {short(day('on 20 Nov'))} to {short(day('on 26 Nov'))} at 15:30",
        f"You confirmed {short(day('on 20 Nov'))}",
    ]


def test_giving_an_undated_task_a_date(client):
    note = save_and_file(client, "Call the bank about the card")
    task = task_of(client, note)
    assert task["due_on"] is None
    client.post(f"/api/tasks/{task['id']}/date", json={"due_on": day("on 22 Nov")})
    assert updates(client, note)[0]["kind"] == "set"
    assert updates(client, note)[0]["text"] == f"Date set: {short(day('on 22 Nov'))}"


def test_date_rules(client):
    note = save_and_file(client, "Attend Statistics meeting on 20 Nov")
    task_id = task_of(client, note)["id"]
    assert client.post(f"/api/tasks/{task_id}/date", json={"due_on": "2026-02-30"}).status_code == 422
    assert client.post(f"/api/tasks/{task_id}/date", json={"due_on": "2026-11-20", "due_time": "25:00"}).status_code == 422
    assert client.post(f"/api/tasks/{task_id}/date", json={"due_on": "2026-11-20", "x": 1}).status_code == 422
    assert client.post("/api/tasks/999999/date", json={"due_on": "2026-11-20"}).status_code == 404
    client.post("/api/auth/logout")
    register(client, "second@example.com")
    assert client.post(f"/api/tasks/{task_id}/date", json={"due_on": "2026-11-20"}).status_code == 404
    assert client.get(f"/api/items/{note['id']}/updates").status_code == 404


# --- editing a note re-reads a confirmed date -----------------------------------------------


def test_editing_the_note_moves_a_confirmed_date_and_asks_again(client):
    note = save_and_file(client, "Attend Statistics meeting on 20 Nov")
    confirm(client, task_of(client, note))
    edit_and_file(client, note, "Attend Statistics meeting on 25 Nov, it was postponed")

    task = task_of(client, note)
    assert task["due_on"] == day("on 25 Nov")
    assert task["timing_confirmed"] is False  # waits for your OK again
    latest = updates(client, note)[0]
    assert latest["kind"] == "note_edit" and latest["needs_confirmation"]
    assert latest["text"] == f"Your edit moved it from {short(day('on 20 Nov'))} to {short(day('on 25 Nov'))}"

    confirm(client, task)
    after = updates(client, note)
    assert after[0]["text"] == f"You confirmed {short(day('on 25 Nov'))}"
    assert not after[1]["needs_confirmation"]
    assert task_of(client, note)["timing_confirmed"] is True


def test_editing_without_a_new_date_keeps_it_confirmed(client):
    note = save_and_file(client, "Attend Statistics meeting on 20 Nov")
    confirm(client, task_of(client, note))
    edit_and_file(client, note, "Attend the Statistics meeting on 20 Nov, room 4")
    task = task_of(client, note)
    assert task["due_on"] == day("on 20 Nov") and task["timing_confirmed"] is True
    assert [u["kind"] for u in updates(client, note)] == ["confirmed"]


def test_analysis_without_an_edit_never_moves_a_confirmed_date(client):
    note = save_and_file(client, "Attend Statistics meeting on 20 Nov")
    task = task_of(client, note)
    client.post(f"/api/tasks/{task['id']}/date", json={"due_on": day("on 27 Nov")})
    assert client.post("/api/analyze").status_code == 200  # Analyze Entire Inbox
    assert client.post("/api/analyze", params={"item_id": note["id"]}).status_code == 200
    task = task_of(client, note)
    assert task["due_on"] == day("on 27 Nov") and task["timing_confirmed"] is True


def test_the_export_includes_your_note_and_the_updates(client):
    client.post("/api/items/url", json={"url": "https://example.com/stats", "context": "for the stats exam"})
    note = save_and_file(client, "Attend Statistics meeting on 20 Nov")
    client.post(f"/api/tasks/{task_of(client, note)['id']}/date", json={"due_on": day("on 26 Nov")})
    export = client.get("/api/items/export.md").text
    assert "### Your note" in export and "for the stats exam" in export
    assert "### Updates" in export
    assert f"Postponed from {short(day('on 20 Nov'))} to {short(day('on 26 Nov'))}" in export



# --- migration 0020 ------------------------------------------------------------------------------


def test_migration_0020_adds_the_date_history(tmp_path, monkeypatch):
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text

    monkeypatch.delenv("DATABASE_URL", raising=False)
    project = Path(__file__).resolve().parent.parent
    database_path = tmp_path / "v19.db"
    config = Config(str(project / "alembic.ini"))
    config.set_main_option("script_location", str(project / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0019_task_priority_and_done")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO tasks (id, text, priority, status, dedup_key, created_at, updated_at, timing_confirmed) "
            "VALUES (1, 'Meeting', 'High', 'open', 'k1', '2026-11-01', '2026-11-02', 1)"))
    command.upgrade(config, "0020_task_date_changes")
    try:
        inspector = inspect(engine)
        assert "task_date_changes" in inspector.get_table_names()
        with engine.begin() as connection:
            assert connection.execute(text("SELECT date_recheck, timing_confirmed FROM tasks")).one() == (0, 1)
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0020_task_date_changes"
        import pytest as _pytest
        from sqlalchemy.exc import IntegrityError
        with _pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO task_date_changes (task_id, task_text, kind, created_at) "
                    "VALUES (1, 'Meeting', 'teleported', '2026-11-07')"))
    finally:
        engine.dispose()
