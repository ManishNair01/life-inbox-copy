"""Change 013: Captain's "Needs you" list. Each kind of card appears and
resolves, cards are ranked, a note gets at most one question at a time (P6),
answers are kept so a card doesn't come back, and each user only sees theirs."""

import importlib
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import login, register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer", "app.captain")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'needs.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("LIFE_INBOX_TIMEZONE", raising=False)
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")

    def unreadable(url):  # never the real internet: every link "fails"
        raise ValueError("The page took too long to answer.")

    monkeypatch.setattr(main, "fetch_url", unreadable)
    # No DNS lookup either: a test never depends on the network.
    monkeypatch.setattr(main, "validate_public_http_url", lambda url: url.strip())
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com")
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def needs(client):
    response = client.get("/api/captain/needs-you")
    assert response.status_code == 200, response.text
    return response.json()


def cards_of(client, kind=None):
    cards = needs(client)["cards"]
    return [card for card in cards if kind is None or card["kind"] == kind]


def resolve(client, card, action, value=None, status=200):
    body = {"action": action} if value is None else {"action": action, "value": value}
    response = client.post(f"/api/captain/needs-you/{card['id']}/resolve", json=body)
    assert response.status_code == status, response.text
    return response.json()


def file_note(client, text):
    note = client.post("/api/items", json={"raw_text": text}).json()
    assert client.post("/api/analyze", params={"item_id": note["id"]}).status_code == 200
    return note


def task_of(client, note):
    return next(t for t in client.get("/api/tasks", params={"status": "all"}).json() if note["id"] in t["source_item_ids"])


def answers(client):
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    try:
        return database.list_captain_answers()
    finally:
        database.set_current_owner_id(None)


def failed_link(client, url="https://example.com/deal"):
    response = client.post("/api/items/url", json={"url": url})
    assert response.status_code in (200, 201), response.text
    item = response.json()
    assert item["processing_status"] == "failed"
    return item


# --- each kind appears and resolves --------------------------------------------------------


def test_a_guessed_date_asks_and_goes_once_answered(client):
    note = file_note(client, "Call mom this weekend")
    [card] = cards_of(client, "date")
    assert card["heading"] == "A date to check"
    assert card["title"] == "Call mom this weekend"
    assert "You wrote “this weekend”" in card["text"]
    assert [a["action"] for a in card["actions"]] == ["check", "not_now"]
    # Confirming it (the card's "Check it" opens the date question) answers it.
    task = task_of(client, note)
    client.post(f"/api/tasks/{task['id']}/date", json={"due_on": task["suggested_due_on"]})
    assert cards_of(client, "date") == []


def test_not_now_is_remembered_until_the_situation_changes(client):
    note = file_note(client, "Call mom this weekend")
    [card] = cards_of(client, "date")
    after = resolve(client, card, "not_now")
    assert all(other["id"] != card["id"] for other in after["cards"])
    assert cards_of(client, "date") == []  # doesn't come back
    database = sys.modules["app.database"]
    saved = answers(client)
    assert saved[0]["card_key"] == card["id"] and saved[0]["answer"] == "not_now"
    # The guess moves to another day: a new question.
    task = task_of(client, note)
    with database.SessionLocal() as session:
        row = session.get(database.TaskRecord, task["id"])
        row.suggested_due_on = (date.fromisoformat(task["suggested_due_on"]) + timedelta(days=7)).isoformat()
        session.commit()
    assert len(cards_of(client, "date")) == 1


def test_a_date_your_edit_moved_asks(client):
    note = file_note(client, "Attend Statistics meeting on 20 Nov")
    task = task_of(client, note)
    client.post(f"/api/tasks/{task['id']}/confirm-timing", json={"timing_text": task["timing_text"]})
    client.put(f"/api/items/{note['id']}", json={"raw_text": "Attend Statistics meeting on 25 Nov, it was postponed"})
    client.post("/api/analyze", params={"item_id": note["id"]})
    [card] = cards_of(client, "moved")
    assert card["heading"] == "Your edit moved a date"
    assert "Your edit moved it from" in card["text"] and "Is that right?" in card["text"]
    assert card["data"]["to"] == task_of(client, note)["due_on"]


def test_a_time_bound_task_without_a_date_offers_set_or_drop(client):
    note = file_note(client, "Call the plumber about the leak")
    [card] = cards_of(client, "no_date")
    assert [a["action"] for a in card["actions"]] == ["set_date", "drop", "not_now"]
    resolve(client, card, "drop")
    assert task_of(client, note)["status"] == "dismissed"
    assert cards_of(client, "no_date") == []


def test_a_failed_capture_takes_a_note_and_is_filed_from_it(client):
    item = failed_link(client)
    [card] = cards_of(client, "failed")
    assert card["heading"] == "Couldn't read this"
    assert [a["action"] for a in card["actions"]] == ["retry", "add_note", "delete", "not_now"]
    resolve(client, card, "add_note", "A coupon for running shoes, ends Friday")
    saved = client.get(f"/api/items/{item['id']}").json()
    assert saved["processing_status"] == "ready" and saved["user_context"] == "A coupon for running shoes, ends Friday"
    assert cards_of(client, "failed") == []
    # Now it can be filed from your words.
    assert client.post("/api/analyze", params={"item_id": item["id"]}).status_code == 200


def test_a_failed_capture_can_be_deleted(client):
    item = failed_link(client)
    [card] = cards_of(client, "failed")
    resolve(client, card, "delete")
    assert client.get(f"/api/items/{item['id']}").status_code == 404
    assert cards_of(client, "failed") == []


def test_a_note_filing_wasnt_sure_about_asks_which_topic(client):
    # No rule fits, so filing doesn't guess (R6): the note waits with no topic
    # and its likeliest topics (here from the words of Skills & projects).
    note = file_note(client, "Self-directed learning about pottery glazes")
    insight = client.get(f"/api/items/{note['id']}/insight").json()
    assert insight["filing_pending"] is True and insight["effective_topic_id"] is None
    assert insight["filing_rule"] == "R6"
    [card] = cards_of(client, "area")
    assert card["text"] == "Life Inbox wasn't sure where this goes. Which topic fits?"
    picks = [a for a in card["actions"] if a["action"] == "pick"]
    assert 1 <= len(picks) <= 2 and card["actions"][-2:] == [
        {"action": "other", "label": "Other topic…", "value": None, "primary": False},
        {"action": "not_now", "label": "Not now", "value": None, "primary": False},
    ]
    resolve(client, card, "pick", picks[0]["value"])
    insight = client.get(f"/api/items/{note['id']}/insight").json()
    assert insight["effective_topic_id"] == picks[0]["value"]
    assert insight["filing_pending"] is False and insight["filed_by"] == "you"
    assert cards_of(client, "area") == []
    answer = answers(client)[0]
    assert answer["answer"] == f"picked:{picks[0]['value']}" and answer["detail"]["picked"] == picks[0]["label"]
    # A topic that wasn't offered is refused.
    resolve(client, {"id": "area:999:none"}, "pick", 1, status=404)


def test_with_no_likely_topic_the_card_leads_with_pick_a_topic(client):
    # A note that shares no words with any topic: no guesses to offer.
    note = file_note(client, "Zxqv plorb")
    [card] = [c for c in cards_of(client, "area") if c["item_id"] == note["id"]]
    assert [a["action"] for a in card["actions"]] == ["other", "not_now"]
    assert card["actions"][0] == {"action": "other", "label": "Pick a topic…", "value": None, "primary": True}
    assert card["text"] == "Life Inbox wasn't sure where this goes. Pick the topic that fits."


def test_an_older_accounts_catch_all_notes_ask_which_topic(client):
    # Accounts from before change 014 still have "Personal / Reference".
    legacy = client.post("/api/topics", json={"name": "Personal / Reference", "description": "Everything else"}).json()
    note = file_note(client, "Nemotron AI tutorial, a tool to try later")
    client.patch(f"/api/items/{note['id']}/insight", json={"user_topic_id": legacy["id"]})
    [card] = [c for c in cards_of(client, "area") if c["item_id"] == note["id"]]
    assert "old catch-all" in card["text"]


def test_unfiled_and_marked_for_review_notes(client):
    unfiled = client.post("/api/items", json={"raw_text": "Ideas for the garden"}).json()
    [card] = cards_of(client, "unfiled")
    assert card["item_id"] == unfiled["id"] and card["actions"][0]["action"] == "file"
    client.post("/api/analyze", params={"item_id": unfiled["id"]})
    assert cards_of(client, "unfiled") == []

    note = file_note(client, "Buy groceries for the week")
    client.patch(f"/api/items/{note['id']}/insight", json={"needs_review": True})
    [card] = cards_of(client, "review")
    resolve(client, card, "done")
    assert client.get(f"/api/items/{note['id']}/insight").json()["needs_review"] is False
    assert cards_of(client, "review") == []


def test_a_topic_without_a_life_area_asks_for_one(client):
    topic = client.post("/api/topics", json={"name": "Chess openings"}).json()
    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        session.get(database.TopicRecord, topic["id"]).bot_key = None
        session.commit()
    [card] = cards_of(client, "topic_area")
    assert card["title"] == "Chess openings"
    assert [a["value"] for a in card["actions"] if a["action"] == "pick"] != []
    resolve(client, card, "pick", "fun")
    topics = {t["id"]: t for t in client.get("/api/topics").json()}
    assert topics[topic["id"]]["bot_key"] == "fun"
    assert cards_of(client, "topic_area") == []
    resolve(client, {"id": card["id"]}, "pick", "fun", status=404)  # already answered


def test_two_things_at_the_same_time_clash(client):
    soon = (date.today() + timedelta(days=3)).isoformat()
    first = task_of(client, file_note(client, "Book a table for date night with Riya"))
    second = task_of(client, file_note(client, "Prepare the Halloween stall at college"))
    client.post(f"/api/tasks/{first['id']}/date", json={"due_on": soon, "due_time": "19:00"})
    client.post(f"/api/tasks/{second['id']}/date", json={"due_on": soon, "due_time": "19:30"})
    [card] = cards_of(client, "clash")
    assert card["heading"] == "Two things at once" and card["title"].endswith("at 19:00")
    assert set(card["data"]["task_ids"]) == {first["id"], second["id"]}
    # A clash is the one question for both notes (P6): their other questions wait.
    clashing = set(card["data"]["item_ids"])
    assert all(other["item_id"] not in clashing for other in cards_of(client) if other["kind"] != "clash")
    resolve(client, card, "ignore")
    assert cards_of(client, "clash") == []
    assert clashing & {other["item_id"] for other in cards_of(client)}  # now they can ask


# --- ranking, one question per note, privacy, rules ------------------------------------------


def test_cards_are_ranked_by_how_soon_they_matter(client):
    database = sys.modules["app.database"]
    topic = client.post("/api/topics", json={"name": "Chess openings"}).json()
    with database.SessionLocal() as session:
        session.get(database.TopicRecord, topic["id"]).bot_key = None
        session.commit()
    file_note(client, "Call the plumber about the leak")       # no date
    file_note(client, "Self-directed learning about pottery glazes")  # which topic
    failed_link(client)                                          # couldn't read
    file_note(client, "Call mom this weekend")                  # a date to check
    kinds = [card["kind"] for card in needs(client)["cards"]]
    assert kinds == ["date", "failed", "area", "no_date", "topic_area"]
    assert needs(client)["total"] == 5


def test_one_question_per_note_at_a_time(client):
    # A guessed date in a note filing wasn't sure about: the date first.
    note = file_note(client, "Meet Utkarsh this Sunday")
    task = task_of(client, note)
    assert task["due_confidence"] == "suggested"
    assert client.get(f"/api/items/{note['id']}/insight").json()["filing_pending"] is True
    mine = [card for card in needs(client)["cards"] if card["item_id"] == note["id"]]
    assert [card["kind"] for card in mine] == ["date"]
    resolve(client, mine[0], "not_now")
    # The second question only after the first is answered.
    mine = [card for card in needs(client)["cards"] if card["item_id"] == note["id"]]
    assert [card["kind"] for card in mine] == ["area"]


def test_each_user_sees_only_their_own_cards(client):
    file_note(client, "Call mom this weekend")
    [card] = cards_of(client, "date")
    client.post("/api/auth/logout")
    register(client, "other@example.com")
    assert needs(client) == {"cards": [], "total": 0}
    resolve(client, card, "not_now", status=404)
    client.post("/api/auth/logout")
    login(client, "owner@example.com")
    assert [c["id"] for c in cards_of(client, "date")] == [card["id"]]


def test_answers_are_checked(client):
    file_note(client, "Call mom this weekend")
    [card] = cards_of(client, "date")
    resolve(client, card, "drop", status=422)        # not one of this card's answers
    resolve(client, card, "teleport", status=422)    # not an answer at all
    response = client.post(f"/api/captain/needs-you/{card['id']}/resolve", json={"action": "not_now", "extra": 1})
    assert response.status_code == 422
    client.post("/api/auth/logout")
    assert client.get("/api/captain/needs-you").status_code == 401


# --- migration 0022 ----------------------------------------------------------------------------


def test_migration_0022_adds_captain_answers(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.exc import IntegrityError

    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "v21.db"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0021_date_provenance")
    command.upgrade(config, "0022_captain_answers")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("captain_answers")}
        assert {"owner_user_id", "card_key", "kind", "answer", "detail", "item_id", "task_id", "topic_id"} <= columns
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO users (id, email, display_name, auth_provider, created_at) "
                "VALUES (77, 'a@example.com', '', 'password', '2026-11-07')"))
            connection.execute(text(
                "INSERT INTO captain_answers (owner_user_id, card_key, kind, answer, created_at) "
                "VALUES (77, 'date:1:2026-11-08', 'date', 'not_now', '2026-11-07')"))
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO captain_answers (owner_user_id, card_key, kind, answer, created_at) "
                    "VALUES (77, 'date:1:2026-11-08', 'date', 'not_now', '2026-11-07')"))
    finally:
        engine.dispose()
