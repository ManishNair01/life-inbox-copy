"""Change 012 (the rest): where each task date came from. A day your words name
goes straight on ("from your note"); a guess waits for your OK ("suggested")
and stays off the calendar and reminders; dates are read from the day you
wrote the note, in your own time zone; migration 0021 sorts existing tasks."""

import importlib
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'provenance.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("LIFE_INBOX_TIMEZONE", raising=False)
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com")
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def parse(phrase, reference=None):
    from app.attention.dates import parse_timing_phrase

    return parse_timing_phrase(phrase, reference=reference).normalized_iso


def file_note(client, text):
    note = client.post("/api/items", json={"raw_text": text}).json()
    assert client.post("/api/analyze", params={"item_id": note["id"]}).status_code == 200
    return note


def task_of(client, note):
    tasks = [t for t in client.get("/api/tasks", params={"status": "all"}).json() if note["id"] in t["source_item_ids"]]
    assert len(tasks) == 1, tasks
    return tasks[0]


def on_calendar(client, note):
    events = client.get("/api/calendar/events", params={"start": "2026-01-01", "end": "2028-12-31"}).json()
    return [e["event_date"] for e in events if e["source_item_id"] == note["id"]]


def backdate(note_id, stamp):
    """Pretend the note was written at `stamp` (UTC ISO)."""
    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        item = session.get(database.InboxItemRecord, note_id)
        item.created_at = stamp
        item.updated_at = None
        session.commit()


# --- where a date stands ---------------------------------------------------------------


@pytest.mark.parametrize("text, phrase", [
    ("Dentist on 12 Nov", "on 12 Nov"),
    ("Call mom tomorrow", "tomorrow"),
    ("Pay the rent in 3 days", "in 3 days"),
])
def test_a_day_your_words_name_goes_straight_on(client, text, phrase):
    note = file_note(client, text)
    task = task_of(client, note)
    assert task["due_confidence"] == "from_note"
    assert task["due_on"] == parse(phrase) and task["suggested_due_on"] is None
    assert task["timing_confirmed"] is False  # nothing to confirm: your words named it
    assert on_calendar(client, note) == [task["due_on"]]


@pytest.mark.parametrize("text, phrase", [
    ("Call mom this weekend", "this weekend"),
    ("Renew the insurance by Friday", "by Friday"),
    ("Book flights in December", "in December"),
    ("Fix the leak asap", "asap"),
])
def test_a_guess_waits_for_your_ok_off_the_calendar(client, text, phrase):
    note = file_note(client, text)
    task = task_of(client, note)
    assert task["due_confidence"] == "suggested"
    assert task["due_on"] is None and task["suggested_due_on"] == parse(phrase)
    assert on_calendar(client, note) == []


def test_confirming_a_suggestion_puts_it_on_the_calendar(client):
    weekend = file_note(client, "Call mom this weekend")
    friday = file_note(client, "Renew the insurance by Friday")

    # From the picker (or the question after saving): the suggested day, as yours.
    task = task_of(client, weekend)
    confirmed = client.post(f"/api/tasks/{task['id']}/date", json={"due_on": task["suggested_due_on"]}).json()
    assert confirmed["due_on"] == task["suggested_due_on"] and confirmed["due_confidence"] == "user_confirmed"
    assert confirmed["suggested_due_on"] is None
    assert on_calendar(client, weekend) == [task["suggested_due_on"]]
    updates = client.get(f"/api/items/{weekend['id']}/updates").json()
    assert updates[0]["kind"] == "confirmed"

    # From a task card's "Confirm date" (it sends the task's own words back).
    other = task_of(client, friday)
    response = client.post(f"/api/tasks/{other['id']}/confirm-timing", json={"timing_text": other["timing_text"]})
    assert response.json()["due_on"] == other["suggested_due_on"]
    assert on_calendar(client, friday) == [other["suggested_due_on"]]


def test_area_status_shows_a_suggestion_with_a_question_mark(client):
    file_note(client, "Call mom this weekend")
    people = {b["key"]: b for b in client.get("/api/bots").json()}["people"]
    assert people["next_task"]["suggested"] is True
    assert people["status"].endswith("?")


# --- dates are read from the day you wrote the note, in your time zone ---------------------


def test_tomorrow_means_the_day_after_you_wrote_it(client):
    note = client.post("/api/items", json={"raw_text": "Call mom tomorrow"}).json()
    written = date.today() - timedelta(days=3)
    backdate(note["id"], f"{written.isoformat()}T09:00:00+00:00")
    assert client.post("/api/analyze").status_code == 200  # analysed days later
    assert task_of(client, note)["due_on"] == (written + timedelta(days=1)).isoformat()


def test_no_day_shift_in_india_time(client, monkeypatch):
    monkeypatch.setenv("LIFE_INBOX_TIMEZONE", "Asia/Kolkata")
    note = client.post("/api/items", json={"raw_text": "Call mom tomorrow"}).json()
    backdate(note["id"], "2026-11-07T19:30:00+00:00")  # 01:00 on Sun 8 Nov in India
    assert client.post("/api/analyze", params={"item_id": note["id"]}).status_code == 200
    assert task_of(client, note)["due_on"] == "2026-11-09"


def test_reminders_follow_real_dates_only(client):
    database = sys.modules["app.database"]
    from app.notifications import service

    named = file_note(client, "Team call today")
    guessed = file_note(client, "Team lunch this weekend")
    me = client.get("/api/auth/me").json()
    user_id = (me.get("user") or me)["id"]
    today = date.fromisoformat(parse("today"))

    def reminders():
        return {task["id"]: task for task in database.list_notification_tasks(user_id)}

    # The morning digest lists the day your note named; a guess only counts as
    # "to review", it is not announced as due.
    tasks = list(reminders().values())
    digest = service._daily_payload(tasks, local_date=today, unscheduled_count=1)
    assert "Team call today" in digest["body"] and "Team lunch" not in digest["body"]

    # Confirm the guess with a time and make it High: the one-hour alert now fires.
    lunch = task_of(client, guessed)
    assert service._eligible_high_priority(reminders()[lunch["id"]], "UTC") is None
    client.patch(f"/api/tasks/{lunch['id']}", json={"priority": "High"})
    client.post(f"/api/tasks/{lunch['id']}/date", json={"due_on": lunch["suggested_due_on"], "due_time": "13:00"})
    due_at = service._eligible_high_priority(reminders()[lunch["id"]], "UTC")
    assert due_at is not None and (due_at.date().isoformat(), due_at.strftime("%H:%M")) == (lunch["suggested_due_on"], "13:00")


# --- migration 0021 ------------------------------------------------------------------------


def test_migration_0021_sorts_existing_dates(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "v20.db"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0020_task_date_changes")
    engine = create_engine(f"sqlite:///{database_path}")
    rows = [
        # id, timing_text, due_on, due_confidence, timing_confirmed
        (1, "this weekend", "2026-11-07", "high", 1),   # you confirmed it
        (2, "tomorrow", "2026-11-08", "high", 0),       # your words named the day
        (3, "on 12 Nov", "2026-11-12", "medium", 0),    # named the day; only the year was guessed
        (4, "this weekend", "2026-11-07", "medium", 0),  # a guess
        (5, "by Friday", "2026-11-13", "medium", 0),    # a guess
        (6, "soon", None, "low", 0),                     # no date
    ]
    with engine.begin() as connection:
        for task_id, timing, due_on, confidence, confirmed in rows:
            connection.execute(text(
                "INSERT INTO tasks (id, text, priority, timing_text, due_on, due_time, due_confidence, "
                "timing_confirmed, status, dedup_key, created_at, updated_at) VALUES "
                "(:id, 'Task', 'Medium', :timing, :due_on, '10:00', :confidence, :confirmed, 'open', :key, "
                "'2026-11-01', '2026-11-01')"
            ), {"id": task_id, "timing": timing, "due_on": due_on, "confidence": confidence,
                "confirmed": confirmed, "key": f"k{task_id}"})
    command.upgrade(config, "0021_date_provenance")
    try:
        with engine.begin() as connection:
            got = connection.execute(text(
                "SELECT id, due_confidence, due_on, suggested_due_on, suggested_due_time FROM tasks ORDER BY id"
            )).all()
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0021_date_provenance"
        assert [tuple(row) for row in got] == [
            (1, "user_confirmed", "2026-11-07", None, None),
            (2, "from_note", "2026-11-08", None, None),
            (3, "from_note", "2026-11-12", None, None),
            (4, "suggested", None, "2026-11-07", "10:00"),
            (5, "suggested", None, "2026-11-13", "10:00"),
            (6, None, None, None, None),
        ]
    finally:
        engine.dispose()
