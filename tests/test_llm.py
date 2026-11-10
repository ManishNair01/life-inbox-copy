"""One path for every AI call (app/llm.py): logging, limits, retries, timeouts.

Every AI call is faked; nothing here talks to NVIDIA or OpenAI.
"""

import importlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import llm
from tests.auth_helpers import register
from tests.voice_fixtures import make_wav_bytes

MODULES = (
    "app.main", "app.database", "app.auth", "app.config", "app.organizer",
    "app.retrieval.ask",
)
APP_DIR = Path(__file__).resolve().parents[1] / "app"


class FakeNotFound(Exception):
    """Looks like openai.NotFoundError: the provider answered 404."""

    status_code = 404


def chat_reply(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def fake_chat(monkeypatch, *replies, seen=None):
    """openai.OpenAI returns a client whose chat answers come from `replies`.

    A reply that is an exception is raised instead of returned.
    """
    import openai

    queue = list(replies)

    def create(**kwargs):
        if seen is not None:
            seen.append(kwargs)
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, Exception):
            raise reply
        return chat_reply(reply(kwargs) if callable(reply) else reply)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: client)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


@pytest.fixture(autouse=True)
def no_retry_wait(monkeypatch):
    monkeypatch.setattr(llm, "RETRY_DELAY_SECONDS", 0)


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'llm.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    for name in ("LIFE_INBOX_AI_TIMEOUT_SECONDS", "NVIDIA_LLM_MODEL", "OPENAI_MODEL", "NVIDIA_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    with TestClient(main.app) as client:
        register(client, "owner@example.com")
        yield SimpleNamespace(client=client, database=database, db_path=tmp_path / "llm.db")
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def logged_calls(database):
    with database.SessionLocal() as session:
        rows = session.scalars(select(database.AiCallRecord).order_by(database.AiCallRecord.id)).all()
        return [
            {column: getattr(row, column) for column in (
                "owner_user_id", "action", "model", "outcome", "attempt",
                "status_code", "input_size", "output_size",
            )}
            for row in rows
        ]


def user_id(database, email="owner@example.com"):
    with database.SessionLocal() as session:
        return session.scalar(select(database.UserRecord.id).where(database.UserRecord.email == email))


# --- one path ---------------------------------------------------------------------


def test_only_the_gateway_creates_ai_clients():
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if path.name != "llm.py" and "OpenAI(" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


# --- the call log -------------------------------------------------------------------


def test_calls_are_logged_per_user_and_never_store_text(app_env, monkeypatch):
    fake_chat(monkeypatch, json.dumps(
        {"parent": "Medicines & doctors", "area": "health", "reason": "It is about medicines."}
    ))
    marker = "Quokka-zebra pill planner"
    response = app_env.client.post(
        "/api/topics/suggest-parent",
        json={"name": marker, "description": "When to take my tablets"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["suggested_parent"]["name"] == "Medicines & doctors"

    calls = logged_calls(app_env.database)
    assert len(calls) == 1
    call = calls[0]
    assert call["owner_user_id"] == user_id(app_env.database)
    assert (call["action"], call["outcome"], call["attempt"]) == ("suggest_parent", "ok", 1)
    assert call["model"] == llm.DEFAULT_MODEL
    assert call["input_size"] > len(marker) and call["output_size"] > 0
    # Neither the prompt nor the answer is written anywhere in the database.
    app_env.database.engine.dispose()
    for suffix in ("", "-wal", "-journal"):
        path = Path(f"{app_env.db_path}{suffix}")
        if path.exists():
            assert marker.encode() not in path.read_bytes()


def test_each_user_only_sees_their_own_calls(app_env, monkeypatch):
    fake_chat(monkeypatch, json.dumps({"parent": None, "reason": ""}))
    app_env.client.post("/api/topics/suggest-parent", json={"name": "Chess", "description": "Openings"})
    app_env.client.post("/api/auth/logout")
    register(app_env.client, "second@example.com")
    app_env.client.post("/api/topics/suggest-parent", json={"name": "Garden", "description": "Plants"})

    database = app_env.database
    for email in ("owner@example.com", "second@example.com"):
        database.set_current_owner_id(user_id(database, email))
        try:
            mine = database.list_ai_calls()
        finally:
            database.set_current_owner_id(None)
        assert len(mine) == 1
        assert mine[0]["action"] == "suggest_parent"


def test_calls_outside_a_signed_in_request_are_not_logged(app_env, monkeypatch):
    fake_chat(monkeypatch, json.dumps({"parent": None, "reason": ""}))
    organizer = importlib.import_module("app.organizer")
    organizer.suggest_parent_topic(
        "Chess", "Openings",
        [{"id": 1, "name": "Study", "description": "", "parent_topic_id": None}],
    )
    assert logged_calls(app_env.database) == []


# --- retries ------------------------------------------------------------------------


def run_as_owner(app_env, fn):
    database = app_env.database
    database.set_current_owner_id(user_id(database))
    try:
        return fn()
    finally:
        database.set_current_owner_id(None)


def test_provider_not_found_gets_one_quick_retry(app_env, monkeypatch):
    fake_chat(monkeypatch, FakeNotFound("404"), "hello")
    assert run_as_owner(app_env, lambda: llm.complete_text("ask", "Hi")) == "hello"
    calls = logged_calls(app_env.database)
    assert [(c["outcome"], c["attempt"], c["status_code"]) for c in calls] == [
        ("error", 1, 404), ("ok", 2, None),
    ]


def test_not_found_twice_gives_up(app_env, monkeypatch):
    fake_chat(monkeypatch, FakeNotFound("404"), FakeNotFound("404"))
    with pytest.raises(FakeNotFound):
        run_as_owner(app_env, lambda: llm.complete_text("ask", "Hi"))
    assert [c["outcome"] for c in logged_calls(app_env.database)] == ["error", "error"]


def test_other_errors_are_not_retried(app_env, monkeypatch):
    fake_chat(monkeypatch, RuntimeError("boom"), "never reached")
    with pytest.raises(RuntimeError):
        run_as_owner(app_env, lambda: llm.complete_text("ask", "Hi"))
    calls = logged_calls(app_env.database)
    assert [(c["outcome"], c["status_code"]) for c in calls] == [("error", None)]


# --- JSON answers -------------------------------------------------------------------


def test_unusable_json_is_logged_invalid_and_not_repaired_by_default(app_env, monkeypatch):
    fake_chat(monkeypatch, "not json at all")
    with pytest.raises(llm.InvalidOutput):
        run_as_owner(app_env, lambda: llm.complete_json("analyze", "Return JSON"))
    calls = logged_calls(app_env.database)
    assert [(c["outcome"], c["attempt"]) for c in calls] == [("invalid", 1)]


def test_one_repair_request_names_the_problem(app_env, monkeypatch):
    seen = []
    fake_chat(monkeypatch, json.dumps({"topic": "Nope"}), json.dumps({"topic": "Study"}), seen=seen)

    def validate(data):
        return None if data["topic"] == "Study" else "Topic 'Nope' does not exist."

    result = run_as_owner(
        app_env, lambda: llm.complete_json("file", "Pick a topic", validate=validate, repair=True)
    )
    assert result == {"topic": "Study"}
    repair_prompt = seen[1]["messages"][0]["content"]
    assert "Topic 'Nope' does not exist." in repair_prompt
    assert repair_prompt.startswith("Pick a topic")
    calls = logged_calls(app_env.database)
    assert [(c["outcome"], c["attempt"]) for c in calls] == [("invalid", 1), ("ok", 2)]


def test_repair_happens_at_most_once(app_env, monkeypatch):
    seen = []
    fake_chat(monkeypatch, "bad", "still bad", "never asked", seen=seen)
    with pytest.raises(llm.InvalidOutput):
        run_as_owner(app_env, lambda: llm.complete_json("file", "Pick", repair=True))
    assert len(seen) == 2


# --- limits and settings ----------------------------------------------------------------


def test_prompt_over_the_limit_is_not_sent(app_env, monkeypatch):
    seen = []
    fake_chat(monkeypatch, "{}", seen=seen)
    with pytest.raises(llm.PromptTooLarge):
        run_as_owner(app_env, lambda: llm.complete_text("file", "x" * 4001, max_prompt_tokens=1000))
    assert seen == []
    calls = logged_calls(app_env.database)
    assert [(c["outcome"], c["input_size"]) for c in calls] == [("too_large", 4001)]


def test_prompt_at_the_limit_is_sent(monkeypatch):
    fake_chat(monkeypatch, "ok")
    assert llm.complete_text("file", "x" * 4000, max_prompt_tokens=1000) == "ok"


def test_every_request_has_a_timeout(monkeypatch):
    import openai

    made = []

    def make(**kwargs):
        made.append(kwargs)
        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_k: chat_reply("ok"))),
            audio=SimpleNamespace(transcriptions=SimpleNamespace(create=lambda **_k: SimpleNamespace(text="hi"))),
        )

    monkeypatch.setattr(openai, "OpenAI", make)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")
    monkeypatch.delenv("LIFE_INBOX_AI_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
    llm.complete_text("ask", "Hi")
    monkeypatch.setenv("LIFE_INBOX_AI_TIMEOUT_SECONDS", "15")
    llm.complete_text("ask", "Hi")
    llm.transcribe("voice_transcribe", file=("a.wav", b"RIFF", "audio/wav"), model="m")
    assert [kwargs["timeout"] for kwargs in made] == [60.0, 15.0, llm.AUDIO_TIMEOUT_SECONDS]
    assert made[0]["base_url"] == llm.DEFAULT_BASE_URL


def test_nvidia_key_prefix_is_restored_but_openai_keys_are_untouched(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_API_KEY", "abc123")
    assert llm.api_key() == "nvapi-abc123"
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-abc123")
    assert llm.api_key() == "nvapi-abc123"
    monkeypatch.delenv("NVIDIA_API_KEY")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Before this change, voice transcription turned this into "nvapi-sk-test".
    assert llm.api_key() == "sk-test"
    assert llm.provider() == "openai"


# --- Ask My Inbox: the NVIDIA 404 seen in the owner's log --------------------------


def seed_book_note(client):
    response = client.post(
        "/api/items",
        json={"raw_text": "Rohan recommended reading Atomic Habits by James Clear; start with chapter 1."},
    )
    assert response.status_code == 200, response.text


def grounded_answer(kwargs):
    prompt = kwargs["messages"][0]["content"]
    citation_id = re.search(r'"citation_id": "([^"]+)"', prompt).group(1)
    return json.dumps({
        "answer": "Rohan recommended Atomic Habits; start with chapter 1.",
        "confidence": "high",
        "citation_ids": [citation_id],
    })


def ask(client):
    response = client.post("/api/ask", json={"question": "What did Rohan recommend about Atomic Habits?"})
    assert response.status_code == 200, response.text
    return response.json()


def test_ask_gets_a_model_answer_through_the_gateway(app_env, monkeypatch):
    seed_book_note(app_env.client)
    fake_chat(monkeypatch, grounded_answer)
    data = ask(app_env.client)
    assert data["mode"] == "llm_grounded"
    assert data["citations"]
    assert [c["action"] for c in logged_calls(app_env.database)] == ["ask"]


def test_ask_survives_one_provider_not_found(app_env, monkeypatch):
    seed_book_note(app_env.client)
    fake_chat(monkeypatch, FakeNotFound("404"), grounded_answer)
    data = ask(app_env.client)
    assert data["mode"] == "llm_grounded"
    calls = logged_calls(app_env.database)
    assert [(c["outcome"], c["status_code"]) for c in calls] == [("error", 404), ("ok", None)]


def test_ask_falls_back_when_not_found_persists(app_env, monkeypatch):
    seed_book_note(app_env.client)
    fake_chat(monkeypatch, FakeNotFound("404"), FakeNotFound("404"))
    data = ask(app_env.client)
    assert data["mode"] == "extractive_fallback"
    assert "Atomic Habits" in data["answer"]


def test_ask_with_an_unusable_answer_falls_back(app_env, monkeypatch):
    seed_book_note(app_env.client)
    fake_chat(monkeypatch, json.dumps({"answer": "x", "confidence": "high", "citation_ids": ["item-999-9"]}))
    data = ask(app_env.client)
    assert data["mode"] == "extractive_fallback"
    # Change 019: one repair call names the failed check, then the quoted answer.
    assert [c["outcome"] for c in logged_calls(app_env.database)] == ["invalid", "invalid"]


# --- voice ---------------------------------------------------------------------------


def test_voice_note_takes_two_calls_transcription_then_filing(app_env, monkeypatch):
    # Change 014: speech-to-text, then the filing call, which also returns the
    # tidied transcript. No separate clean-up call.
    import openai

    def filing_answer(**kwargs):
        import re

        prompt = kwargs["messages"][-1]["content"]
        note_id = int(re.search(r'"id": (\d+)', prompt.split("Notes (JSON):", 1)[1]).group(1))
        return chat_reply(json.dumps({"notes": [{
            "id": note_id, "area": "health", "topic": "Medicines & doctors", "confidence": "high",
            "rule": "R1", "choices": [], "title": "Dentist on Friday", "priority": "Medium", "tags": [],
            "reason": "A dentist visit.", "tasks": [{"task": "Go to the dentist", "when": "on friday",
                                                    "date": None, "time": None}],
            "transcript": "Remember the dentist on Friday.", "summary": None, "action": None,
        }]}))

    client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(
            create=lambda **_k: SimpleNamespace(text="um remember the dentist on friday"))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=filing_answer)),
    )
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: client)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")
    monkeypatch.delenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", raising=False)
    item = app_env.client.post(
        "/api/items/voice", files={"file": ("memo.wav", make_wav_bytes(), "audio/wav")}
    ).json()
    assert item["raw_text"] == "um remember the dentist on friday"  # your words, as heard
    assert app_env.client.post(f"/api/analyze?item_id={item['id']}").status_code == 200
    insight = app_env.client.get(f"/api/items/{item['id']}/insight").json()
    assert insight["cleaned_transcript"] == "Remember the dentist on Friday."
    calls = logged_calls(app_env.database)
    assert [(c["action"], c["outcome"]) for c in calls] == [
        ("voice_transcribe", "ok"), ("filing", "ok"),
    ]
    assert calls[0]["input_size"] > 0  # audio bytes
