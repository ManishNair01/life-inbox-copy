"""Change 011's server side: your priority on tasks (kept apart from the AI's),
when a task was done, each task's life area and reason, migration 0019, and
the Dashboard's numbers (app/attention/glance.py)."""

import importlib
import sys
from datetime import date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.attention.glance import build_glance, local_date
from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'priority.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
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


def add_and_file(client, *texts):
    items = [client.post("/api/items", json={"raw_text": t}).json() for t in texts]
    assert client.post("/api/analyze").status_code == 200
    return items


def task_for(client, item):
    tasks = [t for t in client.get("/api/tasks", params={"status": "all"}).json()
             if item["id"] in t["source_item_ids"]]
    assert tasks, f"no task for item {item['id']}"
    return tasks[0]


# --- your priority ---------------------------------------------------------------------


def test_a_drag_saves_your_priority_and_analysis_keeps_it(client):
    (bill,) = add_and_file(client, "Pay the electricity bill before Friday")
    task = task_for(client, bill)
    ai = task["priority"]
    assert task["ai_priority"] == ai and task["user_priority"] is None
    yours = "Low" if ai != "Low" else "High"

    moved = client.patch(f"/api/tasks/{task['id']}", json={"priority": yours})
    assert moved.status_code == 200, moved.text
    assert moved.json()["priority"] == yours
    assert moved.json()["user_priority"] == yours and moved.json()["ai_priority"] == ai

    # Analysing again refreshes the AI's value but never overwrites yours.
    assert client.post("/api/analyze").status_code == 200
    again = task_for(client, bill)
    assert again["priority"] == yours and again["user_priority"] == yours

    # Your value is the task's priority everywhere, the calendar included.
    events = client.get("/api/calendar/events", params={"start": "2026-01-01", "end": "2027-12-31"}).json()
    assert all(e["priority"] == yours for e in events if e["id"] == task["id"])

    # Clearing it goes back to the AI's.
    cleared = client.patch(f"/api/tasks/{task['id']}", json={"priority": None}).json()
    assert cleared["priority"] == ai and cleared["user_priority"] is None


def test_priority_update_rules(client):
    (bill,) = add_and_file(client, "Pay the electricity bill before Friday")
    task_id = task_for(client, bill)["id"]
    assert client.patch(f"/api/tasks/{task_id}", json={"priority": "Urgent"}).status_code == 422
    assert client.patch(f"/api/tasks/{task_id}", json={}).status_code == 422
    assert client.patch(f"/api/tasks/{task_id}", json={"priority": "Low", "bogus": "x"}).status_code == 422
    assert client.patch("/api/tasks/999999", json={"priority": "Low"}).status_code == 404
    client.post("/api/auth/logout")
    register(client, "second@example.com")
    assert client.patch(f"/api/tasks/{task_id}", json={"priority": "Low"}).status_code == 404


def test_tasks_carry_their_area_and_reason(client):
    bill, lecture = add_and_file(client, "Pay the electricity bill before Friday", "Read the lecture notes tomorrow")
    bill_task = task_for(client, bill)
    assert bill_task["bot_key"] == "money"
    insight = client.get(f"/api/items/{bill['id']}/insight").json()
    assert bill_task["reason"] == insight["rationale"] and bill_task["reason"]
    assert task_for(client, lecture)["bot_key"] == "learn"
    manual = client.post("/api/tasks", json={"text": "Water the plants"}).json()
    assert manual["bot_key"] is None and manual["reason"] is None
    events = client.get("/api/calendar/events", params={"start": "2026-01-01", "end": "2027-12-31"}).json()
    assert {e["bot_key"] for e in events if e["source_item_id"] == lecture["id"]} == {"learn"}


def test_completed_at_follows_the_status(client):
    (lecture,) = add_and_file(client, "Read the lecture notes tomorrow")
    task_id = task_for(client, lecture)["id"]
    assert task_for(client, lecture)["completed_at"] is None
    done = client.post(f"/api/tasks/{task_id}/complete").json()
    assert done["completed_at"]
    assert client.post(f"/api/tasks/{task_id}/reopen").json()["completed_at"] is None
    assert client.post(f"/api/items/{lecture['id']}/complete").status_code == 200
    assert task_for(client, lecture)["completed_at"]


# --- the Dashboard ------------------------------------------------------------------------


def test_dashboard_glance_follows_the_lens(client):
    bill, lecture, dentist = add_and_file(
        client, "Pay the electricity bill before Friday", "Read the lecture notes tomorrow",
        "Book a dentist appointment",
    )
    client.post(f"/api/tasks/{task_for(client, dentist)['id']}/complete")

    glance = client.get("/api/dashboard/glance")
    assert glance.status_code == 200, glance.text
    body = glance.json()
    assert body["captured_this_week"] == 3
    assert body["tasks_done_this_week"] == 1
    assert body["busiest_day"]["count"] == 3
    areas = {row["key"]: row["count"] for row in body["attention"]}
    assert areas["money"] == 1 and areas["learn"] == 1 and areas["health"] == 1 and areas["fun"] == 0
    assert 1 <= len(body["noticed"]) <= 3

    money = client.get("/api/dashboard/glance", params={"bot": "money"}).json()
    assert money["lens"] == "money" and money["captured_this_week"] == 1
    assert money["tasks_done_this_week"] == 0
    assert {row["name"] for row in money["attention"]} == {
        "Bills & subscriptions", "Bank, tax & documents", "Home & errands"}
    assert all(task["bot_key"] == "money" for task in money["coming_up"])
    assert client.get("/api/dashboard/glance", params={"bot": "travel"}).status_code == 422
    # The browser's own time zone decides "today"; a made-up zone is refused.
    assert client.get("/api/dashboard/glance", params={"tz": "Asia/Kolkata"}).status_code == 200
    assert client.get("/api/dashboard/glance", params={"tz": "Mars/Olympus"}).status_code == 422


BOTS = [{"key": k, "name": n} for k, n in (
    ("learn", "Learning & work"), ("money", "Money & home"), ("health", "Health"),
    ("people", "People"), ("fun", "Fun & interests"))]
TOPICS = [
    {"id": 1, "name": "Study", "bot_key": "learn", "parent_topic_id": None},
    {"id": 2, "name": "Python", "bot_key": "learn", "parent_topic_id": 1},
    {"id": 3, "name": "Bills & subscriptions", "bot_key": "money", "parent_topic_id": None},
    {"id": 4, "name": "Trips & places", "bot_key": "fun", "parent_topic_id": None},
]
TODAY = date(2026, 11, 5)  # a Thursday


def note(item_id, day, topic_id, bot_key):
    return {"id": item_id, "created_at": f"{day.isoformat()}T09:00:00+00:00", "topic_id": topic_id, "bot_key": bot_key}


def task(task_id, text, *, status="open", due_on=None, priority="Medium", bot_key=None, completed_at=None, snoozed_until=None):
    return {"id": task_id, "text": text, "status": status, "due_on": due_on, "priority": priority,
            "bot_key": bot_key, "completed_at": completed_at, "snoozed_until": snoozed_until,
            "due_time": None, "timing_confirmed": True, "source_item_ids": [task_id]}


def test_glance_numbers_and_what_captain_noticed():
    items = [
        note(1, TODAY, 2, "learn"), note(2, TODAY - timedelta(days=1), 1, "learn"),
        note(3, TODAY - timedelta(days=2), 1, "learn"), note(4, TODAY, 3, "money"),
        note(5, TODAY - timedelta(days=60), 4, "fun"),
    ]
    tasks = [
        task(1, "Pay the bill", due_on="2026-11-02", priority="High", bot_key="money"),
        task(2, "Revise loops", due_on="2026-11-07", bot_key="learn"),
        task(3, "Call the bank", bot_key="money"),
        task(4, "Done quiz", status="completed", completed_at="2026-11-04T10:00:00+00:00", bot_key="learn"),
        task(5, "Old done", status="completed", completed_at="2026-10-20T10:00:00+00:00", bot_key="learn"),
        task(6, "Snoozed", due_on="2026-11-06", snoozed_until="2026-11-09", bot_key="learn"),
    ]
    glance = build_glance(items=items, tasks=tasks, topics=TOPICS, bots=BOTS, today=TODAY)
    assert (glance["week_start"], glance["week_end"]) == ("2026-11-02", "2026-11-08")
    assert glance["captured_this_week"] == 4 and glance["tasks_done_this_week"] == 1
    assert glance["open_tasks"] == 4
    assert glance["busiest_day"] == {"date": "2026-11-05", "weekday": "Thursday", "count": 2}
    assert [(row["key"], row["count"]) for row in glance["attention"]] == [
        ("learn", 3), ("money", 1), ("health", 0), ("people", 0), ("fun", 0)]
    # Subtopic notes count toward their topic.
    assert glance["growing"] == [{"id": 1, "name": "Study", "count": 3}]
    assert glance["quiet"] == [{"id": 4, "name": "Trips & places", "last_on": "2026-09-06", "days": 60}]
    # From today, in date order; the snoozed task waits; overdue ones aren't "coming up".
    assert [t["text"] for t in glance["coming_up"]] == ["Revise loops"]
    assert glance["noticed"] == [
        "1 task is overdue. The oldest is “Pay the bill”, due Mon 2 Nov.",
        "Learning & work is your busiest area: 3 of 4 notes in the last 30 days.",
        "Health, People and Fun & interests have been quiet for 30 days.",
    ]


def test_glance_with_a_lens_looks_inside_one_area():
    items = [note(1, TODAY, 2, "learn"), note(2, TODAY, 1, "learn"), note(3, TODAY, 3, "money")]
    tasks = [task(1, "Revise loops", due_on="2026-11-07", bot_key="learn"),
             task(2, "Pay the bill", due_on="2026-11-06", bot_key="money")]
    glance = build_glance(items=items, tasks=tasks, topics=TOPICS, bots=BOTS, today=TODAY, lens="learn")
    assert glance["captured_this_week"] == 2
    assert glance["attention"] == [{"id": 1, "name": "Study", "count": 2}]
    assert [t["text"] for t in glance["coming_up"]] == ["Revise loops"]
    assert glance["noticed"] == ["Study is growing: 2 new notes in the last 14 days."]


def test_glance_when_nothing_happened_yet():
    glance = build_glance(items=[], tasks=[], topics=TOPICS, bots=BOTS, today=TODAY)
    assert glance["captured_this_week"] == 0 and glance["busiest_day"] is None
    assert glance["noticed"] == ["A quiet stretch. What you add will show up here."]


def test_days_are_the_users_own():
    # 20:00 UTC on 4 Nov is already 5 Nov in India, and still 4 Nov in California.
    stamp = "2026-11-04T20:00:00+00:00"
    assert local_date(stamp, ZoneInfo("Asia/Kolkata")) == date(2026, 11, 5)
    assert local_date(stamp, ZoneInfo("America/Los_Angeles")) == date(2026, 11, 4)
    assert local_date(stamp, timezone.utc) == date(2026, 11, 4)
    assert local_date(None, timezone.utc) is None and local_date("nope", timezone.utc) is None


# --- migration 0019 ---------------------------------------------------------------------------


def alembic_config(database_path):
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def test_migration_0019_adds_your_priority_and_done_time(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "v18.db"
    config = alembic_config(database_path)
    command.upgrade(config, "0018_five_life_areas")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO tasks (id, text, priority, status, dedup_key, created_at, updated_at) VALUES "
            "(1, 'Done one', 'High', 'completed', 'k1', '2026-10-01', '2026-10-03'), "
            "(2, 'Open one', 'Low', 'open', 'k2', '2026-10-01', '2026-10-02')"
        ))
    command.upgrade(config, "0019_task_priority_and_done")
    try:
        with engine.begin() as connection:
            rows = connection.execute(text(
                "SELECT id, priority, user_priority, completed_at FROM tasks ORDER BY id")).all()
            assert [tuple(row) for row in rows] == [
                (1, "High", None, "2026-10-03"), (2, "Low", None, None)]
            connection.execute(text("UPDATE tasks SET user_priority = 'Medium' WHERE id = 2"))
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0019_task_priority_and_done"
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("UPDATE tasks SET user_priority = 'Urgent' WHERE id = 1"))
    finally:
        engine.dispose()
