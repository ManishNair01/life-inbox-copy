"""Change 016: memory (what Life Inbox learns about you) and secrets in notes.

The AI is always faked. Covers where facts come from (your corrections,
Captain answers, your own words), their lifecycle (suggested → confirmed,
edited, deleted and never suggested again, short-term facts expiring), privacy
per user, the health-memory consent gate, secret notes hidden on screen and
never sent to the AI or kept as memory, and memory in the export."""

import importlib
import json
import sys
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register
from tests.test_filing import entry, notes_in

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")
SECRET_NOTE = "Flat wifi password: Hunter2Blue for the guests"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'memory.db'}")
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


def save(client, text, **fields):
    response = client.post("/api/items", json={"raw_text": text, **fields})
    assert response.status_code == 200, response.text
    return response.json()


def file(client, note):
    response = client.post("/api/analyze", params={"item_id": note["id"]})
    assert response.status_code == 200, response.text
    return response.json()


def topic_id(client, name):
    return next(t["id"] for t in client.get("/api/topics").json() if t["name"] == name)


def memory(client, bot=None):
    response = client.get("/api/memory", params={"bot": bot} if bot is not None else {})
    assert response.status_code == 200, response.text
    return response.json()


def as_owner(client):
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    return database


def fake_ai(monkeypatch, decide, prompts):
    """Every AI call is recorded in `prompts`; filing calls answer with
    `decide(note)` per note, any other call (Ask me) answers "insufficient"."""
    import openai

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        prompts.append(prompt)
        if "Notes (JSON):\n" in prompt:
            answer = {"notes": [decide(note) for note in notes_in(prompt)]}
        else:
            answer = {"answer": "Not in your notes.", "confidence": "insufficient", "citation_ids": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


# --- secrets ----------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "wifi password: Hunter2Blue",
    "My UPI PIN is 4821",
    "OTP 662211 for the bank",
    "Card 4111 1111 1111 1111 exp 09/29",
    "Account no 123456789012 IFSC HDFC0001234",
    "Aadhaar 2345 6789 0123",
    "PAN ABCDE1234F",
    "key nvapi-AbCdEfGhIjKlMnOpQrStUvWx",
])
def test_secrets_are_spotted(text):
    from app.sensitive import looks_secret, mask_secrets

    assert looks_secret(text)
    assert not looks_secret(mask_secrets(text)), mask_secrets(text)


@pytest.mark.parametrize("text", [
    "Lucknow PIN code 226001",
    "Boarding pass for the 6 am flight",
    "Token number 45 at the clinic",
    "Secret santa gift ideas for the team",
    "Call mum at 9876543210",
    "Buy 2 kg rice and 12 eggs",
])
def test_ordinary_notes_are_not_secrets(text):
    from app.sensitive import looks_secret

    assert not looks_secret(text)


def test_masking_keeps_the_label():
    from app.sensitive import mask_secrets

    assert mask_secrets("Wifi password: Hunter2Blue, ask Raj") == "Wifi password: ••••, ask Raj"


@pytest.mark.parametrize("text, masked", [
    # The value comes after who it's for: hide the value, never "for".
    ("My Password for oracle is Aditya@2026", "My Password for oracle is ••••"),
    ("pin for the locker is 4821", "pin for the locker is ••••"),
    ("wifi password at home - sunrise99", "wifi password at home - ••••"),
    ("password for my gmail account: Qw3rty!x", "password for my gmail account: ••••"),
    ("my gmail password is abc123", "my gmail password is ••••"),
    ("password is sunshine", "password is ••••"),
    ("PIN 4821", "PIN ••••"),
    # No "is": the safety net still hides the password-like word.
    ("My Password for oracle Aditya@2026", "My Password for oracle ••••"),
])
def test_masking_hides_the_value_not_the_next_word(text, masked):
    from app.sensitive import looks_secret, mask_secrets

    assert looks_secret(text)
    assert mask_secrets(text) == masked
    assert not looks_secret(masked)


def test_a_secret_note_filed_without_ai_never_keeps_the_password_in_its_title(client):
    # No AI key in tests: the offline matcher files it, from a masked copy.
    note = save(client, "My Password for oracle is Aditya@2026")
    file(client, note)
    insight = client.get(f"/api/items/{note['id']}/insight").json()
    assert "Aditya@2026" not in (insight["effective_title"] or "")
    cards = client.get("/api/captain/needs-you").json()["cards"]
    assert all("Aditya@2026" not in json.dumps(card) for card in cards)


def test_marking_a_secret_note_done_never_stores_the_password(client):
    note = save(client, "My Password for oracle is Aditya@2026")
    assert client.post(f"/api/items/{note['id']}/complete").status_code == 200

    (task,) = client.get("/api/tasks?status=completed").json()
    assert "Aditya@2026" not in task["text"]
    assert task["text"] == "My Password for oracle is ••••"


@pytest.mark.parametrize("text", [
    "Change the wifi password before the 15th",
    "Reset my password tomorrow",
    "Ask Raj for the wifi password",
])
def test_talking_about_a_password_is_not_a_secret(text):
    from app.sensitive import looks_secret, mask_secrets

    assert not looks_secret(text)
    assert mask_secrets(text) == text


def test_a_secret_note_is_hidden_on_screen_and_never_reaches_the_ai(client, monkeypatch):
    prompts = []
    fake_ai(monkeypatch, lambda note: entry(note["id"], "Home & errands", "money"), prompts)
    secret = save(client, SECRET_NOTE)
    plain = save(client, "Pay the electricity bill on Friday")
    file(client, secret)
    file(client, plain)

    assert prompts, "the plain note was filed by the AI"
    assert all("Hunter2Blue" not in prompt for prompt in prompts)
    assert all(note["id"] != secret["id"] for prompt in prompts if "Notes (JSON):\n" in prompt
               for note in notes_in(prompt))
    # It's still filed (offline, from a masked copy).
    insight = client.get(f"/api/items/{secret['id']}/insight").json()
    assert insight["filed_by"] == "offline"
    assert "Hunter2Blue" not in (insight["effective_title"] or "")

    item = client.get(f"/api/items/{secret['id']}").json()
    assert item["looks_secret"] is True
    assert item["raw_text"] == SECRET_NOTE  # the real text stays yours (Edit, Show)
    assert item["secret_masked"]["raw_text"] == "Flat wifi password: •••• for the guests"
    assert client.get(f"/api/items/{plain['id']}").json()["secret_masked"] is None


def test_search_and_ask_never_show_or_send_a_secret(client, monkeypatch):
    prompts = []
    fake_ai(monkeypatch, lambda note: entry(note["id"], "Home & errands", "money"), prompts)
    save(client, SECRET_NOTE)

    hits = client.get("/api/search", params={"q": "wifi password"}).json()
    assert hits and all("Hunter2Blue" not in hit["excerpt"] for hit in hits)

    response = client.post("/api/ask", json={"question": "What is the wifi password?"})
    assert response.status_code == 200, response.text
    assert all("Hunter2Blue" not in prompt for prompt in prompts)
    assert "Hunter2Blue" not in response.text


# --- where facts come from ----------------------------------------------------------------


def test_moving_a_note_is_remembered_as_your_choice(client):
    note = save(client, "Ideas for the college fest stalls")
    file(client, note)
    target = topic_id(client, "Work & career")
    response = client.patch(f"/api/items/{note['id']}/insight", json={"user_topic_id": target})
    assert response.status_code == 200, response.text

    facts = memory(client)["facts"]
    assert len(facts) == 1
    fact = facts[0]
    assert fact["text"].startswith("You filed “") and fact["text"].endswith("under Work & career.")
    assert (fact["kind"], fact["status"], fact["source_kind"]) == ("example", "confirmed", "correction")
    assert fact["source_item_ids"] == [note["id"]]
    assert memory(client, "learn")["facts"] == facts
    assert memory(client, "money")["facts"] == []


def test_a_priority_or_date_you_set_is_remembered(client):
    note = save(client, "Renew the gym membership")
    file(client, note)
    task = client.post("/api/tasks", json={"text": "Renew the gym membership"}).json()
    assert client.patch(f"/api/tasks/{task['id']}", json={"priority": "High"}).status_code == 200
    due = (date.today() + timedelta(days=3)).isoformat()
    assert client.post(f"/api/tasks/{task['id']}/date", json={"due_on": due}).status_code == 200

    facts = {fact["kind"]: fact for fact in memory(client)["facts"]}
    assert facts["example"]["text"] == "You set “Renew the gym membership” to High priority."
    assert facts["short_term"]["text"].startswith("“Renew the gym membership” is on ")
    assert facts["short_term"]["valid_until"] == (date.fromisoformat(due) + timedelta(days=7)).isoformat()
    plans = memory(client)["coming_up"]
    assert [(plan["text"], plan["due_on"], plan["confirmed"]) for plan in plans] == [
        ("Renew the gym membership", due, True)]


def test_facts_from_your_words_are_suggested_then_confirmed_when_seen_again(client, monkeypatch):
    prompts = []
    fact = "You run your college's events"

    def decide(note):
        return entry(note["id"], "Work & career", "learn", facts=[fact, "Your wifi password is Hunter2Blue"])

    fake_ai(monkeypatch, decide, prompts)
    first = save(client, "As events head I need to book the auditorium for the fest")
    file(client, first)
    facts = memory(client)["facts"]
    assert [(f["text"], f["status"], f["source_kind"], f["kind"], f["bot_key"]) for f in facts] == [
        (fact, "suggested", "your_words", "long_term", "learn")]  # the secret one was never kept

    second = save(client, "Events team meeting: plan the fest budget")
    file(client, second)
    again = memory(client)["facts"]
    assert len(again) == 1
    assert again[0]["status"] == "confirmed" and again[0]["times_seen"] == 2
    assert again[0]["source_item_ids"] == sorted([first["id"], second["id"]])
    assert "facts" in prompts[0] and "THEIR OWN words" in prompts[0]


def test_a_captain_area_answer_is_remembered(client):
    database = as_owner(client)
    row = database.remember("Your topic “Cricket” belongs to Fun & interests.", kind="example",
                            source_kind="needs_you", bot_key="fun", status="confirmed")
    assert row["source_kind"] == "needs_you"
    assert [f["text"] for f in memory(client, "fun")["facts"]] == [row["text"]]


# --- lifecycle ------------------------------------------------------------------------------


def test_confirm_edit_and_delete_a_fact(client):
    database = as_owner(client)
    fact = database.remember("You live in Gurugram", kind="long_term", source_kind="your_words")
    assert fact["status"] == "suggested"

    confirmed = client.patch(f"/api/memory/{fact['id']}", json={"status": "confirmed"}).json()
    assert confirmed["status"] == "confirmed"
    edited = client.patch(f"/api/memory/{fact['id']}", json={"text": "You live in Gurugram, Sector 45"}).json()
    assert (edited["text"], edited["source_kind"]) == ("You live in Gurugram, Sector 45", "you")
    assert client.patch(f"/api/memory/{fact['id']}", json={"text": "My PIN is 4821"}).status_code == 422
    assert client.patch(f"/api/memory/{fact['id']}", json={"status": "deleted"}).status_code == 422
    assert client.patch(f"/api/memory/{fact['id']}", json={"bogus": 1}).status_code == 422

    assert client.delete(f"/api/memory/{fact['id']}").status_code == 204
    assert memory(client)["facts"] == []
    with database.SessionLocal() as session:
        row = session.get(database.MemoryFactRecord, fact["id"])
        assert (row.status, row.text) == ("deleted", "")  # the words are erased
    # Deleted means never suggested again.
    assert database.remember("You live in Gurugram, Sector 45", kind="long_term", source_kind="your_words") is None
    assert client.patch(f"/api/memory/{fact['id']}", json={"status": "confirmed"}).status_code == 404


def test_short_term_facts_expire(client):
    from app.attention.dates import today_in_configured_tz

    database = as_owner(client)
    yesterday = (today_in_configured_tz() - timedelta(days=1)).isoformat()  # the server's today, not this PC's
    kept = database.remember("“Team lunch” is on Monday.", kind="short_term", source_kind="correction",
                             bot_key="people", status="confirmed", valid_until=yesterday)
    assert kept is not None
    assert memory(client)["facts"] == []
    export = client.get("/api/items/export.md").text
    assert "“Team lunch” is on Monday. · expired" in export
    # A medical fact needs health consent, whatever area it came from.
    assert database.remember("“Dentist” is on Monday.", kind="short_term", source_kind="correction",
                             bot_key="people", status="confirmed") is None


def test_memory_is_private_to_each_user(client):
    database = as_owner(client)
    fact = database.remember("You run your college's events", kind="long_term", source_kind="your_words")
    client.post("/api/auth/logout")
    register(client, "someone@example.com")
    assert memory(client)["facts"] == []
    assert client.patch(f"/api/memory/{fact['id']}", json={"status": "confirmed"}).status_code == 404
    assert client.delete(f"/api/memory/{fact['id']}").status_code == 404
    assert "college" not in client.get("/api/items/export.md").text


def test_unknown_area_is_refused(client):
    assert client.get("/api/memory", params={"bot": "travel"}).status_code == 422
    assert client.get("/api/memory", params={"bot": "captain"}).status_code == 200


# --- health consent ---------------------------------------------------------------------------


def test_health_memory_needs_your_consent(client, monkeypatch):
    prompts = []
    fake_ai(monkeypatch, lambda note: entry(note["id"], "Medicines & doctors", "health",
                                            facts=["Your mother takes thyroid tablets"]), prompts)
    database = as_owner(client)
    assert client.get("/api/settings").json()["health_memory_consent"] is False

    file(client, save(client, "Refill mum's thyroid tablets"))
    assert memory(client)["facts"] == []
    assert database.remember("You see a dentist twice a year", kind="long_term", source_kind="you") is None
    other = database.remember("You like long walks", kind="long_term", source_kind="you", status="confirmed")
    assert client.patch(f"/api/memory/{other['id']}", json={"text": "You see the doctor on Mondays"}).status_code == 422

    assert client.patch("/api/settings", json={"health_memory_consent": True}).json()["health_memory_consent"] is True
    file(client, save(client, "Mum's thyroid tablets: one every morning"))
    facts = memory(client, "health")["facts"]
    assert [(f["text"], f["bot_key"]) for f in facts] == [("Your mother takes thyroid tablets", "health")]
    assert memory(client)["health_memory_consent"] is True

    # Switching it off deletes what it held.
    client.patch("/api/settings", json={"health_memory_consent": False})
    assert memory(client, "health")["facts"] == []
    assert "thyroid" not in client.get("/api/items/export.md").text.split("## What Life Inbox learned about you")[-1]
    with database.SessionLocal() as session:
        rows = session.query(database.MemoryFactRecord).filter_by(bot_key="health").all()
        assert rows and all((row.status, row.text) == ("deleted", "") for row in rows)


# --- settings and export -----------------------------------------------------------------------


def test_settings_defaults_and_checks(client):
    settings = client.get("/api/settings").json()
    assert settings == {
        "health_memory_consent": False, "ai_processing": True, "catchup_day": "sun", "catchup_time": "19:00",
        "last_seen_at": None, "last_catchup_at": None, "last_weekly_review_at": None, "onboarding_done": False,
    }
    assert client.patch("/api/settings", json={"catchup_time": "25:00"}).status_code == 422
    assert client.patch("/api/settings", json={"catchup_day": "someday"}).status_code == 422
    assert client.patch("/api/settings", json={"last_seen_at": "2026-01-01"}).status_code == 422
    assert client.patch("/api/settings", json={"catchup_day": "sat", "catchup_time": "08:30"}).json()["catchup_day"] == "sat"


def test_export_includes_memory_with_its_source(client):
    note = save(client, "Ideas for the college fest stalls")
    file(client, note)
    client.patch(f"/api/items/{note['id']}/insight", json={"user_topic_id": topic_id(client, "Work & career")})
    export = client.get("/api/items/export.md").text
    assert "## What Life Inbox learned about you" in export
    assert f"· confirmed (from note #{note['id']})" in export


def test_secret_notes_never_become_examples_for_the_ai(client):
    database = as_owner(client)
    secret = save(client, SECRET_NOTE)
    file(client, secret)
    client.patch(f"/api/items/{secret['id']}/insight", json={"user_topic_id": topic_id(client, "Home & errands")})
    assert database.filing_examples([secret["id"]]) == {}  # never shown to the AI as a similar note
    # And the memory of moving it never holds the secret.
    assert all("Hunter2Blue" not in fact["text"] for fact in memory(client)["facts"])


def test_plural_medical_words_need_health_consent_too(client):
    # Found in change 024: "medicines" slipped past a pattern that only knew "medicine".
    database = as_owner(client)
    for text in ("You buy your parents' medicines", "You see two doctors", "You visit hospitals often"):
        assert database.remember(text, kind="long_term", source_kind="you") is None, text


def test_moving_a_secret_note_never_puts_its_title_in_memory(client):
    # A masked title can still carry part of a secret ("… code is 4821"),
    # so a note that holds one never feeds memory, not even its title.
    note = save(client, "My PIN 4821 for the locker, code is 4821")
    file(client, note)
    client.patch(f"/api/items/{note['id']}/insight", json={"user_topic_id": topic_id(client, "Bank, tax & documents")})
    assert memory(client)["facts"] == []
