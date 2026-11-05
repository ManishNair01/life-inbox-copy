"""Regression tests for multi-user isolation and startup/config fixes."""

import logging
from types import SimpleNamespace

from tests.auth_helpers import login, register
from tests.test_calendar import client  # noqa: F401  (shared fixture)


def _switch_user(client, email):
    client.post("/api/auth/logout")
    register(client, email)


def test_startup_health_check_does_not_swallow_errors(client, caplog):
    import app.main as main

    # DEBUG so the original bug (a NameError logged at debug level) is caught.
    with caplog.at_level(logging.DEBUG):
        main._check_startup_health()
    assert "Startup migration check skipped" not in caplog.text


def test_calendar_draft_is_only_confirmable_by_its_owner(client):
    task = client.post(
        "/api/tasks",
        json={"text": "Dentist visit", "priority": "High", "due_on": "2030-01-15"},
    ).json()
    preview = client.post(
        "/api/calendar/preview", json={"task_id": task["id"]}
    )
    assert preview.status_code == 200, preview.text
    draft_id = preview.json()["draft_id"]

    _switch_user(client, "intruder@example.com")
    stolen = client.post("/api/calendar/confirm", json={"draft_id": draft_id})
    assert stolen.status_code == 404

    client.post("/api/auth/logout")
    login(client, "owner@example.com")
    ok = client.post("/api/calendar/confirm", json={"draft_id": draft_id})
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "confirmed_mock"


def test_analysis_by_another_user_keeps_my_relations(client):
    for _ in range(2):
        client.post("/api/items", json={"raw_text": "Buy milk and eggs tomorrow"})
    assert client.post("/api/analyze").status_code == 200
    mine = client.get("/api/relations").json()
    assert mine, "expected a duplicate relation between the two notes"

    _switch_user(client, "other@example.com")
    client.post("/api/items", json={"raw_text": "Plan a trip to Jaipur"})
    assert client.post("/api/analyze").status_code == 200
    assert client.get("/api/relations").json() == []
    # Another user cannot dismiss my relation either.
    assert (
        client.post(f"/api/relations/{mine[0]['id']}/dismiss").status_code == 404
    )

    client.post("/api/auth/logout")
    login(client, "owner@example.com")
    still_mine = client.get("/api/relations").json()
    assert [r["id"] for r in still_mine] == [r["id"] for r in mine]


def _fake_openai(captured):
    class _Completions:
        def create(self, **kwargs):
            msg = SimpleNamespace(content="cleaned")
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    class _Transcriptions:
        def create(self, **kwargs):
            return SimpleNamespace(text="raw words")

    class FakeOpenAI:
        def __init__(self, base_url=None, api_key=None):
            captured.append(api_key)
            self.chat = SimpleNamespace(completions=_Completions())
            self.audio = SimpleNamespace(transcriptions=_Transcriptions())

    return FakeOpenAI


def _run_transcribe(monkeypatch, captured):
    import openai

    from app.capture.voice_extract import transcribe_audio

    monkeypatch.setattr(openai, "OpenAI", _fake_openai(captured))
    return transcribe_audio(
        b"RIFF\x00\x00\x00\x00WAVEdata",
        original_filename="n.wav",
        mime_type="audio/wav",
    )


def test_nvapi_prefix_only_applied_to_nvidia_key(monkeypatch):
    captured = []
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-plain-openai")
    _run_transcribe(monkeypatch, captured)
    assert captured and set(captured) == {"sk-plain-openai"}

    captured.clear()
    monkeypatch.setenv("NVIDIA_API_KEY", "bare-key")
    _run_transcribe(monkeypatch, captured)
    assert captured and set(captured) == {"nvapi-bare-key"}


# --- analysis must not outlive deleted / completed notes ---------------------


def _analyzed_ids(client):
    data = client.get("/api/analyze/latest").json()
    return {n["id"] for b in data["buckets"] for n in b["notes"]}


def _topic_total(client):
    return sum(t["item_count"] for t in client.get("/api/topics").json())


def test_deleted_note_disappears_from_saved_analysis(client):
    keep = client.post("/api/items", json={"raw_text": "Call the bank on Monday"}).json()
    gone = client.post("/api/items", json={"raw_text": "Buy groceries tomorrow"}).json()
    assert client.post("/api/analyze").status_code == 200
    assert {keep["id"], gone["id"]} <= _analyzed_ids(client)

    assert client.delete(f"/api/items/{gone['id']}").status_code == 204
    assert _analyzed_ids(client) == {keep["id"]}
    dash = client.get("/api/dashboard").json()
    ids = {n["id"] for b in dash["analysis"]["buckets"] for n in b["notes"]}
    assert gone["id"] not in ids
    assert _topic_total(client) == 1


def test_completed_note_leaves_analysis_and_topic_counts(client):
    keep = client.post("/api/items", json={"raw_text": "Call the bank on Monday"}).json()
    done = client.post("/api/items", json={"raw_text": "Dentist appointment tomorrow"}).json()
    assert client.post("/api/analyze").status_code == 200
    assert _topic_total(client) == 2

    assert client.post(f"/api/items/{done['id']}/complete").status_code == 200
    assert _analyzed_ids(client) == {keep["id"]}
    assert _topic_total(client) == 1

    # Reopening the task brings it back (nothing was destroyed).
    task = client.get("/api/tasks?status=completed").json()[0]
    client.post(f"/api/tasks/{task['id']}/reopen")
    assert done["id"] in _analyzed_ids(client)
    assert _topic_total(client) == 2


def test_tonight_is_parsed_as_today():
    from datetime import date

    from app.attention.dates import parse_timing_phrase

    ref = date(2026, 11, 5)
    for phrase in ("tonight", "dinner tonight at 8pm", "this evening"):
        parsed = parse_timing_phrase(phrase, reference=ref)
        assert parsed.due_date == ref, phrase
        assert parsed.needs_confirmation is False


def test_calendar_preview_works_for_tonight_task(client):
    client.post("/api/items", json={"raw_text": "I need to go to dinner at 8pm tonight."})
    client.post("/api/analyze")
    task = client.get("/api/tasks").json()[0]
    client.post(
        f"/api/tasks/{task['id']}/confirm-timing",
        json={"timing_text": "tonight"},
    )
    res = client.post("/api/calendar/preview", json={"task_id": task["id"]})
    assert res.status_code == 200, res.text


# --- manually added dated task must reach the calendar -----------------------


def _js_function_body(source: str, name: str) -> str:
    start = source.index(f"async function {name}(")
    end = source.index("\nasync function ", start + 1)
    return source[start:end]


def test_manual_dated_task_is_returned_as_calendar_event(client):
    task = client.post(
        "/api/tasks",
        json={"text": "Manual dated task", "priority": "Medium", "due_on": "2030-03-12"},
    ).json()
    events = client.get("/api/calendar/events?start=2030-03-01&end=2030-03-31").json()
    assert [e["id"] for e in events] == [task["id"]]
    assert events[0]["event_date"] == "2030-03-12"
    assert events[0]["source_item_id"] is None


def test_quick_task_form_refreshes_calendar(client):
    source = client.get("/static/app.js").text.replace("\r\n", "\n")
    body = _js_function_body(source, "createQuickTask")
    assert "loadCalendarEvents()" in body
