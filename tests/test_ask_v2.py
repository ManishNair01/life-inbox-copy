"""Change 019: Ask me v2 (the AI is always faked).

Routing by the lens, evidence from notes + remembered facts + the tasks on
the days asked about, every citation checked (one repair call), the honest
"not found" with no AI call, and "How I answered"."""

import importlib
import json
import re
import sys
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ask.db'}")
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


def today():
    from app.attention.dates import today_in_configured_tz

    return today_in_configured_tz()


def ask(client, question, **extra):
    response = client.post("/api/ask", json={"question": question, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def fake_ai(monkeypatch, answers, prompts):
    """Each AI call gets the next answer: a dict, or a function of the prompt."""
    import openai

    queue = list(answers)

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        prompts.append(prompt)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        answer = answer(prompt) if callable(answer) else answer
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


def ids_in(prompt, prefix):
    return re.findall(rf'"citation_id": "({prefix}[^"]*)"', prompt)


def filed(client, text):
    note = client.post("/api/items", json={"raw_text": text}).json()
    client.post("/api/analyze", params={"item_id": note["id"]})
    return note


def dated(client, text, days, time=None, confirm=True):
    task = client.post("/api/tasks", json={"text": text}).json()
    day = (today() + timedelta(days=days)).isoformat()
    if confirm:
        client.post(f"/api/tasks/{task['id']}/date", json={"due_on": day, **({"due_time": time} if time else {})})
    else:
        database = sys.modules["app.database"]
        with database.SessionLocal() as session:
            row = session.get(database.TaskRecord, task["id"])
            row.suggested_due_on, row.due_confidence = day, "suggested"
            session.commit()
    return task, day


# --- the period, by code ---------------------------------------------------------------------


def test_the_days_a_question_asks_about():
    from app.retrieval.ask import question_period

    wednesday = date(2026, 11, 11)
    def span(question):
        found = question_period(question, wednesday)
        return (found["start"], found["end"]) if found else None

    assert span("What's on today?") == ("2026-11-11", "2026-11-11")
    assert span("anything tomorrow") == ("2026-11-12", "2026-11-12")
    assert span("What do I have this week?") == ("2026-11-09", "2026-11-15")
    assert span("plans for next week") == ("2026-11-16", "2026-11-22")
    assert span("what did I do last week") == ("2026-11-02", "2026-11-08")
    assert span("this weekend?") == ("2026-11-14", "2026-11-15")
    assert span("What's on Saturday?") == ("2026-11-14", "2026-11-14")
    assert span("what happened last Monday") == ("2026-11-09", "2026-11-09")
    assert span("on 20 Nov") == ("2026-11-20", "2026-11-20")
    assert span("Dec 3rd plans") == ("2026-12-03", "2026-12-03")
    assert span("this month") == ("2026-11-01", "2026-11-30")
    assert span("What did Rohan recommend?") is None


# --- not found: no call -------------------------------------------------------------------------


def test_nothing_matches_means_no_ai_call_and_no_guess(client, monkeypatch):
    prompts = []
    fake_ai(monkeypatch, [{"answer": "Paris", "confidence": "high", "citation_ids": []}], prompts)
    client.post("/api/items", json={"raw_text": "Buy milk"})
    data = ask(client, "What is the capital of France?")
    assert data["answer"] == "I couldn't find that in your notes, so I won't guess."
    assert data["confidence"] == "insufficient" and data["citations"] == []
    assert prompts == [] and data["how"]["ai_calls"] == 0


# --- evidence, citations, and the repair ------------------------------------------------------------


def test_tasks_for_a_named_day_are_evidence_and_a_guess_can_be_confirmed(client, monkeypatch):
    call, call_day = dated(client, "Call mom", 1, confirm=False)
    prompts = []
    fake_ai(monkeypatch, [lambda prompt: {"answer": "Call mom is suggested for tomorrow.", "confidence": "high",
                                          "citation_ids": [f"t{call['id']}"]}], prompts)
    data = ask(client, "What do I have tomorrow?")
    assert data["mode"] == "llm_grounded"
    assert [task["task_id"] for task in data["tasks"]] == [call["id"]]
    assert data["tasks"][0]["confirmed"] is False
    [action] = data["suggested_actions"]
    assert action["kind"] == "confirm_date" and action["task_id"] == call["id"] and action["due_on"] == call_day
    assert "date_confirmed\": false" in prompts[0]
    # Nothing ran: the date is still only suggested until you tap it.
    task = next(t for t in client.get("/api/tasks?status=open").json() if t["id"] == call["id"])
    assert task["due_on"] is None and task["suggested_due_on"] == call_day
    assert data["how"]["period"].startswith("tomorrow (") and data["how"]["tasks_read"] == 1


def test_remembered_facts_are_evidence_with_their_notes(client, monkeypatch):
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    note = client.post("/api/items", json={"raw_text": "As events head I book the college auditorium"}).json()
    fact = database.remember("You run your college's events", kind="long_term", source_kind="you",
                             status="confirmed", item_ids=[note["id"]])
    database.remember("You like long walks", kind="long_term", source_kind="you", status="confirmed")
    database.set_current_owner_id(None)
    prompts = []
    fake_ai(monkeypatch, [lambda prompt: {"answer": "You run your college's events.", "confidence": "high",
                                          "citation_ids": [f"m{fact['id']}"]}], prompts)
    data = ask(client, "Which college events do I run?")
    assert data["mode"] == "llm_grounded"
    assert data["facts"] == [{"id": fact["id"], "text": "You run your college's events", "source_item_ids": [note["id"]]}]
    assert "long walks" not in prompts[0]  # only facts that share words with the question
    assert data["how"]["memory_used"] == 1 and data["how"]["facts_considered"] == 1


def test_a_bad_citation_gets_one_repair_then_the_quoted_answer(client, monkeypatch):
    note = filed(client, "Rohan recommended reading Atomic Habits by James Clear")
    prompts = []
    bad = {"answer": "Invented.", "confidence": "high", "citation_ids": ["item-999-1"]}
    fake_ai(monkeypatch, [bad, bad], prompts)
    data = ask(client, "What did Rohan recommend about Atomic Habits?")
    assert len(prompts) == 2  # the answer, then one repair naming the failed check
    assert "not in the evidence" in prompts[1]
    assert data["mode"] == "extractive_fallback" and data["answer_kind"] == "grounded_summary"
    assert any(c["item_id"] == note["id"] for c in data["citations"])
    assert data["how"]["ai_calls"] == 2


def test_a_claim_without_a_citation_is_repaired(client, monkeypatch):
    filed(client, "Rohan recommended reading Atomic Habits by James Clear")
    prompts = []
    good = lambda prompt: {"answer": "Rohan recommended Atomic Habits.", "confidence": "high",
                           "citation_ids": ids_in(prompt, "item")[:1],
                           "claims": [{"claim": "Rohan recommended Atomic Habits", "citation_ids": ids_in(prompt, "item")[:1]}]}
    uncited = {"answer": "Rohan recommended Atomic Habits.", "confidence": "high", "citation_ids": [],
               "claims": [{"claim": "Rohan recommended Atomic Habits", "citation_ids": []}]}
    fake_ai(monkeypatch, [uncited, good], prompts)
    data = ask(client, "What did Rohan recommend about Atomic Habits?")
    assert len(prompts) == 2 and "cites nothing" in prompts[1]
    assert data["mode"] == "llm_grounded" and data["claims"][0]["citation_ids"]


# --- the lens -------------------------------------------------------------------------------------


def test_the_lens_reads_only_that_area(client, monkeypatch):
    money = filed(client, "Pay the electricity bill before Friday")
    learn = filed(client, "Study for the statistics quiz before Friday")
    data = ask(client, "What do I need to do before Friday?", bot="money")
    assert {c["item_id"] for c in data["citations"]} <= {money["id"]}
    assert data["how"]["areas"] == ["money"] and data["how"]["lens"] == "money"
    everything = ask(client, "What do I need to do before Friday?")
    assert {money["id"], learn["id"]} <= set(everything["how"]["notes_read"])
    assert set(everything["how"]["areas"]) >= {"money", "learn"}
    assert client.post("/api/ask", json={"question": "anything?", "bot": "travel"}).status_code == 422
