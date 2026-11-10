"""Change 020: the weekly review, topic proposals, bot summaries and the
greeting (the AI is always faked).

One weekly call per user; proposals never create a topic without you (P1);
no duplicate or similar topics, and "Don't suggest this" is remembered;
facts to confirm; summaries reused until their area changes; the greeting
once a day; nothing at all without AI or with the AI switch off."""

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer", "app.review", "app.scout")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'review.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("LIFE_INBOX_TIMEZONE", raising=False)
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    monkeypatch.setattr(importlib.import_module("app.llm"), "RETRY_DELAY_SECONDS", 0)
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com")
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def owner(client):
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    user_id = (me.get("user") or me)["id"]
    database.set_current_owner_id(user_id)
    return database, user_id


def calls(action=None):
    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        return [row.action for row in session.query(database.AiCallRecord).order_by(database.AiCallRecord.id)
                if action is None or row.action == action]


def fake_ai(monkeypatch, answer_for):
    """answer_for(action-ish prompt) -> dict. Filing gets a plain offline-like answer."""
    import openai

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer_for(prompt))))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


def old_account(database, user_id, days=30):
    database.get_settings(user_id)
    with database.SessionLocal() as session:
        row = session.get(database.UserSettingsRecord, user_id)
        row.created_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        session.commit()


def hostel_notes(client):
    """Three Money & home notes that share "hostel" (no topic says hostel). Filed offline."""
    ids = []
    for text in ("Pay the hostel mess fees", "Hostel laundry token rules", "Ask the hostel warden about the bill"):
        note = client.post("/api/items", json={"raw_text": text}).json()
        client.post("/api/analyze", params={"item_id": note["id"]})
        ids.append(note["id"])
    database = sys.modules["app.database"]
    topic = next(t for t in client.get("/api/topics").json() if t["name"] == "Home & errands")
    with database.SessionLocal() as session:
        for item_id in ids:  # make sure they sit in Money & home, as the offline matcher may differ
            row = session.get(database.ItemInsightRecord, item_id)
            row.topic_id, row.user_topic_id, row.filing_pending = topic["id"], None, 0
        session.commit()
    return ids, topic


def review_answer(prompt, **extra):
    groups = json.loads(prompt.split("Groups of notes that no topic fits yet (JSON):\n", 1)[1].split("\n\nAnswer", 1)[0])
    answer = {"merge": [], "trim": [], "new_facts": [], "proposals": [
        {"group": g["group"], "name": "Hostel life", "description": "Hostel fees, rules and the warden.",
         "parent": g["main_topics"][-1] if "Home & errands" not in g["main_topics"] else "Home & errands"}
        for g in groups]}
    answer.update(extra)
    return answer


def answers(prompt):
    if "You tidy a personal Life Inbox's memory once a week." in prompt:
        return review_answer(prompt)
    if "Write Captain's one-line greeting" in prompt:
        return {"greeting": "Good to see you; the hostel fees are waiting."}
    if "Write the summary line" in prompt:
        return {"summary": "Hostel fees and errands live here."}
    raise AssertionError("unexpected AI call: " + prompt[:80])


# --- the weekly review -----------------------------------------------------------------------------


def test_one_weekly_review_per_user_per_week(client, monkeypatch):
    database, user_id = owner(client)
    hostel_notes(client)
    old_account(database, user_id)
    fake_ai(monkeypatch, answers)
    client.get("/api/captain/greeting")
    client.get("/api/captain/greeting")
    assert calls("weekly_review") == ["weekly_review"]
    assert database.get_settings(user_id)["last_weekly_review_at"]
    def a_week_passes():
        with database.SessionLocal() as session:
            row = session.get(database.UserSettingsRecord, user_id)
            row.last_weekly_review_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
            session.commit()

    # A week later, with nothing new to review (the group already waits as a
    # proposal), no call is spent.
    a_week_passes()
    client.get("/api/captain/greeting")
    assert calls("weekly_review") == ["weekly_review"]
    # The week after, with a fact to look at, it runs again.
    database.remember("You live in the college hostel", kind="long_term", source_kind="you", status="confirmed")
    a_week_passes()
    client.get("/api/captain/greeting")
    assert calls("weekly_review") == ["weekly_review", "weekly_review"]


def test_a_new_account_waits_a_week(client, monkeypatch):
    hostel_notes(client)
    fake_ai(monkeypatch, answers)
    client.get("/api/captain/greeting")
    assert calls("weekly_review") == []


def test_a_proposal_never_makes_a_topic_without_you(client, monkeypatch):
    database, user_id = owner(client)
    ids, parent = hostel_notes(client)
    old_account(database, user_id)
    fake_ai(monkeypatch, answers)
    before = {t["name"] for t in client.get("/api/topics").json()}
    client.get("/api/captain/greeting")
    assert {t["name"] for t in client.get("/api/topics").json()} == before  # P1: nothing made yet

    cards = client.get("/api/captain/needs-you").json()["cards"]
    [card] = [c for c in cards if c["kind"] == "proposal"]
    assert card["title"] == "Hostel life" and card["heading"] == "A new topic?"
    assert [a["action"] for a in card["actions"]] == ["create", "rename", "not_now", "never"]
    response = client.post(f"/api/captain/needs-you/{card['id']}/resolve", json={"action": "create", "value": "Hostel"})
    assert response.status_code == 200, response.text
    topic = next(t for t in client.get("/api/topics").json() if t["name"] == "Hostel")
    assert topic["parent_topic_id"] == parent["id"] and topic["bot_key"] == "money"
    assert topic["proposed_by"] == "money" and sorted(topic["evidence_item_ids"]) == sorted(ids) and topic["approved_at"]
    for item_id in ids:
        assert client.get(f"/api/items/{item_id}/insight").json()["effective_topic_id"] == topic["id"]


def test_dont_suggest_this_is_remembered_and_similar_names_are_dropped(client, monkeypatch):
    database, user_id = owner(client)
    hostel_notes(client)
    old_account(database, user_id)
    fake_ai(monkeypatch, answers)
    client.get("/api/captain/greeting")
    [card] = [c for c in client.get("/api/captain/needs-you").json()["cards"] if c["kind"] == "proposal"]
    client.post(f"/api/captain/needs-you/{card['id']}/resolve", json={"action": "never"})

    review = importlib.import_module("app.review")
    facts = database.review_facts(user_id)
    assert all(group["word"] != "hostel" for group in review.note_groups(facts))  # never offered again
    # A name like an existing topic is dropped by code, whatever the AI says.
    groups = [{"group": "g1", "bot_key": "money", "word": "bills", "signature": "money:bills",
               "item_ids": [1, 2, 3], "titles": ["a", "b", "c"]}]
    _, checked = review.check_review({"proposals": [{"group": "g1", "name": "Home & errands", "parent": "Home & errands"}]},
                                     facts, groups)
    assert checked["proposals"] == []
    _, checked = review.check_review({"proposals": [{"group": "g1", "name": "Rent", "parent": "Not a main topic"}]},
                                     facts, groups)
    assert checked["proposals"] == []


def test_facts_to_confirm_and_merging(client, monkeypatch):
    database, user_id = owner(client)
    old_account(database, user_id)
    one = database.remember("You run the college events", kind="long_term", source_kind="you", status="confirmed")
    two = database.remember("You organise your college's events", kind="long_term", source_kind="you", status="confirmed")
    stale = database.remember("You are planning the Goa trip", kind="long_term", source_kind="you", status="confirmed")

    def weekly(prompt):
        if "once a week" in prompt:
            return {"merge": [{"keep": f"m{one['id']}", "drop": [f"m{two['id']}"]}], "trim": [f"m{stale['id']}"],
                    "new_facts": [{"fact": "You lead the college fest team", "from": [f"m{one['id']}"]},
                                  {"fact": "Your wifi password is Hunter2Blue", "from": [f"m{one['id']}"]},
                                  {"fact": "An unsupported guess", "from": ["m99999"]}],
                    "proposals": []}
        return answers(prompt)

    fake_ai(monkeypatch, weekly)
    client.get("/api/captain/greeting")
    live = {f["text"]: f for f in client.get("/api/memory").json()["facts"]}
    assert "You organise your college's events" not in live and "You are planning the Goa trip" not in live
    assert live["You run the college events"]["times_seen"] == 2
    suggested = live["You lead the college fest team"]
    assert (suggested["status"], suggested["source_kind"]) == ("suggested", "weekly_review")
    assert not any("Hunter2Blue" in text or "guess" in text for text in live)

    [card] = [c for c in client.get("/api/captain/needs-you").json()["cards"] if c["kind"] == "fact"]
    assert card["title"] == "You lead the college fest team"
    assert [a["action"] for a in card["actions"]] == ["yes", "no", "edit"]
    client.post(f"/api/captain/needs-you/{card['id']}/resolve", json={"action": "yes"})
    assert {f["text"]: f for f in client.get("/api/memory").json()["facts"]}["You lead the college fest team"]["status"] == "confirmed"


# --- summaries and the greeting -----------------------------------------------------------------------


def test_summaries_are_reused_until_the_area_changes(client, monkeypatch):
    hostel_notes(client)
    fake_ai(monkeypatch, answers)
    first = client.get("/api/bots/money/summary").json()
    assert first["ai"] is False  # code's, while the AI writes it in the background
    assert calls("bot_summary") == ["bot_summary"]
    second = client.get("/api/bots/money/summary").json()
    assert second == {"bot_key": "money", "summary": "Hostel fees and errands live here.", "ai": True}
    client.get("/api/bots/money/summary")
    assert calls("bot_summary") == ["bot_summary"]  # unchanged area: no new call
    database = sys.modules["app.database"]
    with database.SessionLocal() as session:  # the area changes
        row = session.query(database.ItemInsightRecord).first()
        row.updated_at = datetime.now(timezone.utc).isoformat() + "x"
        session.commit()
    assert client.get("/api/bots/money/summary").json()["ai"] is False
    assert calls("bot_summary") == ["bot_summary", "bot_summary"]
    assert client.get("/api/bots/travel/summary").status_code == 422


def test_the_greeting_is_written_once_a_day(client, monkeypatch):
    fake_ai(monkeypatch, answers)
    first = client.get("/api/captain/greeting").json()
    assert first["ai"] is False
    second = client.get("/api/captain/greeting").json()
    assert second == {"text": "Good to see you; the hostel fees are waiting.", "ai": True}
    client.get("/api/captain/greeting")
    assert calls("greeting") == ["greeting"]


def test_nothing_runs_without_ai_or_with_the_switch_off(client, monkeypatch):
    database, user_id = owner(client)
    hostel_notes(client)
    old_account(database, user_id)
    greeting = client.get("/api/captain/greeting").json()  # no AI key
    assert greeting["ai"] is False and greeting["text"]
    assert client.get("/api/bots/money/summary").json()["ai"] is False
    assert calls() == []
    fake_ai(monkeypatch, answers)
    client.patch("/api/settings", json={"ai_processing": False})
    client.get("/api/captain/greeting")
    client.get("/api/bots/money/summary")
    assert calls() == []
