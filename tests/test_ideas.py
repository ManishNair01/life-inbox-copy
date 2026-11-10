"""Change 014a: thought-to-action. A commitment becomes a task; a maybe is
asked about first; a someday idea stays with its note; a thought is nothing."""

import importlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DHABA = ("When I was travelling yesterday, from Gurugram to Lucknow, I found a Dhaba near Mathura "
         "which I want to visit when I will travel on that route again")
RAHUL = "I should probably call Rahul about our Jaipur trip."


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ideas.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
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


def file_note(client, text):
    note = client.post("/api/items", json={"raw_text": text}).json()
    assert client.post("/api/analyze", params={"item_id": note["id"]}).status_code == 200
    return note


def tasks_of(client, note):
    return [t for t in client.get("/api/tasks", params={"status": "all"}).json() if note["id"] in t["source_item_ids"]]


def ideas_of(client, note):
    return client.get(f"/api/items/{note['id']}/ideas").json()


def cards(client, kind=None):
    return [c for c in client.get("/api/captain/needs-you").json()["cards"] if kind is None or c["kind"] == kind]


def test_offline_intent():
    from app.filing import offline_intent

    assert offline_intent("Visit the dhaba I want to visit when I will travel on that route again") == "someday"
    assert offline_intent(RAHUL) == "tentative"
    assert offline_intent("Maybe try the new gym") == "tentative"
    assert offline_intent("Pay rent to landlord by 5th") == "commitment"
    assert offline_intent("Call mom tomorrow") == "commitment"


def test_a_someday_idea_stays_with_its_note_and_never_asks(client):
    note = file_note(client, DHABA)
    assert tasks_of(client, note) == []
    [idea] = ideas_of(client, note)
    assert idea["intent"] == "someday" and "Dhaba" in idea["text"]
    assert [c for c in cards(client) if c["item_id"] == note["id"] and c["kind"] in ("no_date", "idea")] == []
    # Not on the calendar or in the task lists.
    assert client.get("/api/tasks").json() == []


def test_a_maybe_is_asked_about_before_it_becomes_a_task(client):
    note = file_note(client, RAHUL)
    assert tasks_of(client, note) == []
    [card] = cards(client, "idea")
    assert card["heading"] == "Make this a task?" and "maybe" in card["text"]
    assert [a["action"] for a in card["actions"]] == ["add", "not_now"]
    client.post(f"/api/captain/needs-you/{card['id']}/resolve", json={"action": "add"})
    [task] = tasks_of(client, note)
    assert "Rahul" in task["text"] and task["status"] == "open"
    assert ideas_of(client, note) == [] and cards(client, "idea") == []


def test_not_now_dismisses_a_maybe_for_good(client):
    note = file_note(client, RAHUL)
    [card] = cards(client, "idea")
    client.post(f"/api/captain/needs-you/{card['id']}/resolve", json={"action": "not_now"})
    assert cards(client, "idea") == [] and ideas_of(client, note) == []
    client.post("/api/analyze", params={"item_id": note["id"]})  # filed again: not suggested again
    assert cards(client, "idea") == [] and tasks_of(client, note) == []


def test_a_commitment_is_still_a_task_straight_away(client):
    note = file_note(client, "Pay rent to landlord by 5th")
    [task] = tasks_of(client, note)
    assert task["status"] == "open" and ideas_of(client, note) == []


def test_an_idea_can_be_added_from_the_note_page(client):
    note = file_note(client, DHABA)
    [idea] = ideas_of(client, note)
    task = client.post(f"/api/ideas/{idea['id']}/add").json()
    assert task["status"] == "open" and task["source_item_ids"] == [note["id"]]
    assert ideas_of(client, note) == []
    client.post("/api/auth/logout")
    register(client, "other@example.com")
    assert client.post(f"/api/ideas/{idea['id']}/add").status_code == 404


def test_the_ai_labels_intent_and_refiling_turns_a_wrong_task_into_an_idea(client, monkeypatch):
    import openai

    note = client.post("/api/items", json={"raw_text": DHABA}).json()
    answers = iter(["commitment", "someday"])

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        assert '"intent": "commitment"' in prompt and "someday" in prompt
        entry = {"id": note["id"], "area": "fun", "topic": "Trips & places", "confidence": "high", "rule": "R5",
                 "choices": [], "title": "Dhaba near Mathura", "priority": "Low", "tags": [], "reason": "A place to visit.",
                 "tasks": [{"task": "Visit the Dhaba near Mathura", "intent": next(answers),
                            "when": "when I travel on that route again", "date": None, "time": None}],
                 "transcript": None, "summary": None, "action": None}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"notes": [entry]})))])

    monkeypatch.setattr(openai, "OpenAI", lambda **_k: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")
    client.post("/api/analyze", params={"item_id": note["id"]})
    assert len(tasks_of(client, note)) == 1  # the AI first called it a commitment
    client.post("/api/analyze", params={"item_id": note["id"]})
    assert tasks_of(client, note) == []  # filed again as someday: the task goes, the idea stays
    assert [i["intent"] for i in ideas_of(client, note)] == ["someday"]


def test_migration_0025_adds_task_ideas(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'v24.db'}")
    command.upgrade(config, "0024_link_cards")
    command.upgrade(config, "0025_task_ideas")
    engine = create_engine(f"sqlite:///{tmp_path / 'v24.db'}")
    try:
        assert {"text", "timing_text", "intent", "status", "task_id"} <= {c["name"] for c in inspect(engine).get_columns("task_ideas")}
    finally:
        engine.dispose()
