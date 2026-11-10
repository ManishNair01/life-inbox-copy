"""Change 014: filing v2, one checked AI call per note (the AI is always faked).

Covers the build plan's list: batching; the prompt's sections and size; code's
checks and the repair call; the fallback, and Needs you when unsure; voice in 2
calls (tests/test_llm.py); retiring the catch-all and re-sorting in batches;
the offline matcher on the research doc's 37-note table; at most 1.2 calls per
note; and never a topic that doesn't exist (tests/test_topics.py too)."""

import importlib
import json
import re
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register
from tests.filing_replay import SCENARIOS, TABLE

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'filing.db'}")
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


def notes_in(prompt: str) -> list[dict]:
    """The notes a filing prompt sends (its "Notes (JSON):" section)."""
    body = prompt.split("Notes (JSON):\n", 1)[1].split("\nAnswer with ONLY this JSON", 1)[0]
    return json.loads(body)


def fake_ai(monkeypatch, decide, prompts=None):
    """The AI answers every filing call with `decide(note) -> entry` for each
    note in the prompt (or `decide` raises / returns raw text)."""
    import openai

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        if prompts is not None:
            prompts.append(prompt)
        answer = decide(prompt) if getattr(decide, "whole_prompt", False) else {
            "notes": [decide(note) for note in notes_in(prompt)]
        }
        content = answer if isinstance(answer, str) else json.dumps(answer)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


def entry(note_id, topic, area, **extra):
    base = {"id": note_id, "area": area, "topic": topic, "confidence": "high", "rule": "R5",
            "choices": [], "title": "A title", "priority": "Medium", "tags": [], "reason": "Test.",
            "tasks": [], "transcript": None, "summary": None, "action": None}
    base.update(extra)
    return base


def save(client, text, **fields):
    return client.post("/api/items", json={"raw_text": text, **fields}).json()


def file(client, note):
    response = client.post("/api/analyze", params={"item_id": note["id"]})
    assert response.status_code == 200, response.text
    return response.json()


def insight(client, note):
    return client.get(f"/api/items/{note['id']}/insight").json()


def topic_id(client, name):
    return next(t["id"] for t in client.get("/api/topics").json() if t["name"] == name)


def calls(action="filing"):
    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        return [(row.action, row.outcome) for row in session.query(database.AiCallRecord).order_by(database.AiCallRecord.id)
                if action is None or row.action == action]


def as_owner(client):
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    return database


# --- the offline matcher on the research doc's table --------------------------------------


def default_topics():
    from app import bots

    return [{"id": i, "name": name, "description": None, "bot_key": bot, "origin": "built_in",
             "is_built_in": True, "archived": False, "parent_topic_id": None}
            for i, (name, bot) in enumerate(bots.DEFAULT_TOPIC_BOT.items(), start=1)]


def test_offline_matcher_files_the_research_table():
    # Tuned against this very table, so it checks the floor, not real accuracy.
    from app.filing import offline_file

    topics = default_topics()
    names = {t["id"]: t["name"] for t in topics}
    wrong = []
    for number, note, _area, expected, _rule in TABLE:
        got = offline_file({"id": number, **note}, topics)
        if names.get(got["topic"]) != expected:
            wrong.append((number, expected, names.get(got["topic"])))
    assert wrong == []


def test_offline_matcher_never_guesses_wrong_on_the_scenarios():
    from app.filing import offline_file

    topics = default_topics()
    names = {t["id"]: t["name"] for t in topics}
    for note, _area, expected in SCENARIOS:
        got = offline_file({"id": 1, **note}, topics)
        # Right, or it asks (R6) with no topic: never a wrong guess.
        assert got["topic"] is None or names[got["topic"]] == expected, note
        if got["topic"] is None:
            assert got["rule"] == "R6" and got["confidence"] == "low"


def test_offline_rules_go_in_order_and_your_words_come_first():
    from app.filing import offline_file

    topics = default_topics()
    names = {t["id"]: t["name"] for t in topics}

    def placed(note):
        got = offline_file({"id": 1, **note}, topics)
        return names.get(got["topic"]), got["rule"]

    assert placed({"text": "Buy Crocin and cough syrup"}) == ("Medicines & doctors", "R1")  # R1 before shopping
    assert placed({"text": "Health insurance renews 3 Jan"}) == ("Bank, tax & documents", "R2")
    assert placed({"text": "Bruno's rabies shot at the vet"}) == ("Home & errands", "R5")  # pets aren't Health
    # A source: your purpose beats its content (R3); its tasks come only from your words.
    pasta = offline_file({"id": 1, "source": "url", "source_title": "White sauce pasta", "text": "Buy cream. Call the shop.",
                          "context": "for my date night"}, topics)
    assert names[pasta["topic"]] == "Occasions & gifts" and pasta["rule"] == "R3"
    assert pasta["tasks"] == []


# --- level 1: the prompt -------------------------------------------------------------------


def test_prompt_sections_and_size(client):
    filing = sys.modules.get("app.filing") or importlib.import_module("app.filing")
    database = as_owner(client)
    try:
        topics = database.list_topics_from_db()
        long_words = "my own words " * 400  # about 5,200 characters
        long_source = "source text " * 900
        notes = [{"id": i, "text": long_source, "source": "url", "source_title": "A page", "context": long_words}
                 for i in range(1, 6)]
        prompt = filing.build_prompt(notes, topics)
        single = filing.build_prompt([{"id": 9, "text": "Call mom tomorrow", "created_at": "x"}], topics)
    finally:
        database.set_current_owner_id(None)
    assert len(prompt) <= filing.PROMPT_LIMIT_CHARS  # about 3,000 tokens
    for rule in ("R1. Anything medical goes to Health", "R2. Your own bills", "R3. The purpose in your note",
                 "R4. A college's or employer's", "R5. Otherwise the subject decides", "R6. Still unclear"):
        assert rule in single
    assert "A date never decides the category." in single
    # Regression (owner's bird note): no stretching a topic to fit; that's R6.
    assert "Never stretch a topic to fit" in single
    assert date.today().isoformat() in single or "time zone UTC" in single
    assert "time zone UTC" in single
    sent = notes_in(prompt)
    # Your words and the source are separate, and both are cut.
    assert all(len(n["your_words"]) <= filing.WORDS_LIMIT and len(n["source"]["text"]) <= filing.SOURCE_LIMIT for n in sent)
    assert all(n["your_words"].startswith("my own words") and n["source"]["text"].startswith("source text") for n in sent)
    # The catch-all is never offered.
    assert "Personal / Reference" not in single


# --- level 2 and 3: code checks, then one repair call ------------------------------------


def test_code_checks_the_answer():
    from app.filing import check_answer

    topics = default_topics()
    notes = [{"id": 1}, {"id": 2}]
    _, problems = check_answer({"notes": [
        entry(1, "Made-up topic", "learn"),
        entry(1, "Study", "learn"),
        entry(7, "Study", "learn"),
    ]}, notes, topics)
    text = " ".join(problems)
    assert "\"Made-up topic\" doesn't exist" in text and "appears twice" in text
    assert "Unknown note id 7" in text and "Note 2 is missing" in text
    _, problems = check_answer({"notes": [
        entry(1, "Study", "fun"),
        entry(2, "Study", "learn", tasks=[{"task": "Quiz", "when": "on 31 Feb", "date": "2026-02-31", "time": "25:00"}]),
    ]}, notes, topics)
    text = " ".join(problems)
    assert "belongs to area learn, not fun" in text and "not a real date" in text
    answers, problems = check_answer({"notes": [entry(1, "“study”", "learn"), entry(2, None, None, rule="R6",
                                     confidence="low", choices=["Study", "Skills & projects"])]}, notes, topics)
    assert problems == []
    assert answers[2]["topic"] is None and len(answers[2]["choices"]) == 2


def test_a_bad_answer_gets_one_repair_call(client, monkeypatch):
    note = save(client, "Revise for the statistics quiz")
    prompts = []
    answers = iter([
        lambda n: entry(n["id"], "Statistics", "learn"),  # a topic that doesn't exist
        lambda n: entry(n["id"], "Study", "learn", rule="R5", reason="A course quiz."),
    ])
    current = {}

    def decide(n):
        if n["id"] not in current:
            current[n["id"]] = 0
        return next(answers)(n)

    fake_ai(monkeypatch, decide, prompts)
    file(client, note)
    assert insight(client, note)["effective_topic_id"] == topic_id(client, "Study")
    assert insight(client, note)["filed_by"] == "ai" and insight(client, note)["filing_rule"] == "R5"
    assert len(prompts) == 2 and "\"Statistics\" doesn't exist" in prompts[1]
    assert calls() == [("filing", "invalid"), ("filing", "ok")]


def test_when_the_ai_fails_the_offline_matcher_files_it(client, monkeypatch):
    note = save(client, "Pay rent to landlord by 5th")

    def broken(_prompt):
        raise RuntimeError("provider down")

    broken.whole_prompt = True
    fake_ai(monkeypatch, broken)
    result = file(client, note)
    assert result["mode"] == "fallback_after_api_error"
    got = insight(client, note)
    assert got["effective_topic_id"] == topic_id(client, "Bills & subscriptions")
    assert got["filed_by"] == "offline" and got["filing_rule"] == "R2"


# --- level 4: unsure, so it asks you -------------------------------------------------------


def test_an_unsure_answer_waits_in_needs_you_with_its_choices(client, monkeypatch):
    note = save(client, "Nemotron video, saved without a note")
    fake_ai(monkeypatch, lambda n: entry(n["id"], None, None, rule="R6", confidence="low",
                                         choices=["Skills & projects", "Watch, read & listen"]))
    file(client, note)
    got = insight(client, note)
    assert got["filing_pending"] is True and got["effective_topic_id"] is None
    assert got["filing_choices"] == [topic_id(client, "Skills & projects"), topic_id(client, "Watch, read & listen")]
    [card] = [c for c in client.get("/api/captain/needs-you").json()["cards"] if c["kind"] == "area"]
    assert [a["label"] for a in card["actions"] if a["action"] == "pick"] == ["Skills & projects", "Watch, read & listen"]
    # No topic was set, so nothing counts it.
    assert all(t["item_count"] == 0 for t in client.get("/api/topics").json() if t["name"] == "Skills & projects")


# --- what the AI adds: summary, next step, a suggested day -------------------------------------


def test_the_ai_suggests_the_day_for_a_guess_but_never_for_a_named_day(client, monkeypatch):
    guess = save(client, "Call mom this weekend")
    named = save(client, "Dentist tomorrow")
    soon = (date.today() + timedelta(days=4)).isoformat()

    def decide(n):
        if "mom" in n["your_words"]:
            return entry(n["id"], "Family", "people", tasks=[{"task": "Call mom", "when": "this weekend", "date": soon, "time": None}])
        return entry(n["id"], "Medicines & doctors", "health", rule="R1",
                     tasks=[{"task": "Dentist", "when": "tomorrow", "date": "2030-01-01", "time": None}])

    fake_ai(monkeypatch, decide)
    file(client, guess)
    file(client, named)
    tasks = {t["text"]: t for t in client.get("/api/tasks").json()}
    assert tasks["Call mom"]["suggested_due_on"] == soon and tasks["Call mom"]["due_on"] is None  # still waits for your OK
    from app.attention.dates import parse_timing_phrase

    # Your words win: "tomorrow" as the server reads it (its time zone), not the AI's date.
    assert tasks["Dentist"]["due_on"] == parse_timing_phrase("tomorrow").normalized_iso


def test_a_source_gets_a_summary_and_a_next_step(client, monkeypatch):
    database = sys.modules["app.database"]
    item = client.post("/api/items", json={"raw_text": "A recipe for paneer tikka."}).json()
    with database.SessionLocal() as session:
        row = session.get(database.InboxItemRecord, item["id"])
        row.item_type, row.user_context, row.title = "url", "try this", "Paneer tikka | YouTube"
        session.commit()
    fake_ai(monkeypatch, lambda n: entry(n["id"], "Cooking", "fun", summary="A paneer tikka recipe. It takes 30 minutes.",
                                         action="Try this recipe"))
    file(client, item)
    got = insight(client, item)
    assert got["ai_summary"] == "A paneer tikka recipe. It takes 30 minutes." and got["suggested_action"] == "Try this recipe"


# --- batching: notes saved while a call runs share the next one ------------------------------


def test_notes_saved_while_a_call_runs_go_together(client, monkeypatch):
    first, second, third = (save(client, text) for text in ("Buy milk", "Buy eggs", "Buy atta"))
    started, release = threading.Event(), threading.Event()
    batches = []

    def decide(prompt):
        sent = notes_in(prompt)
        batches.append([n["id"] for n in sent])
        if len(batches) == 1:
            started.set()
            release.wait(5)
        return {"notes": [entry(n["id"], "Home & errands", "money") for n in sent]}

    decide.whole_prompt = True
    fake_ai(monkeypatch, decide)
    filing = importlib.import_module("app.filing")
    database = sys.modules["app.database"]
    owner = (client.get("/api/auth/me").json().get("user") or client.get("/api/auth/me").json())["id"]

    def run(note):
        database.set_current_owner_id(owner)
        filing.file_items([note["id"]])

    threads = [threading.Thread(target=run, args=(first,))]
    threads[0].start()
    assert started.wait(5)
    threads += [threading.Thread(target=run, args=(note,)) for note in (second, third)]
    for thread in threads[1:]:
        thread.start()
    time.sleep(0.3)  # both are now waiting for the running call
    release.set()
    for thread in threads:
        thread.join(5)
    assert batches == [[first["id"]], sorted([second["id"], third["id"]])] or batches == [[first["id"]], [second["id"], third["id"]]] or batches == [[first["id"]], [third["id"], second["id"]]]
    assert all(insight(client, note)["effective_topic_id"] == topic_id(client, "Home & errands") for note in (first, second, third))


def test_calls_per_note_stay_under_one_point_two(client, monkeypatch):
    for _number, note, *_ in TABLE[:15]:
        save(client, note.get("text") or note.get("context") or "x")
    topics = {t["name"]: t for t in client.get("/api/topics").json()}
    fake_ai(monkeypatch, lambda n: entry(n["id"], "Study", topics["Study"]["bot_key"]))
    for item in client.get("/api/items").json():
        file(client, item)
    assert len(calls()) / 15 <= 1.2


# --- re-sorting, the catch-all, a new topic, deleting a topic ----------------------------------


def test_resort_everything_files_25_notes_per_call_and_leaves_yours(client, monkeypatch):
    for index in range(30):
        save(client, f"Groceries list number {index}")
    mine = save(client, "Book club picks")
    file(client, mine)
    client.patch(f"/api/items/{mine['id']}/insight", json={"user_topic_id": topic_id(client, "Watch, read & listen")})
    plan_offline = client.get("/api/filing/resort-plan").json()
    assert plan_offline == {"notes": 30, "calls": 0, "per_call": 25, "ai": False}
    prompts = []
    fake_ai(monkeypatch, lambda n: entry(n["id"], "Home & errands", "money"), prompts)
    assert client.get("/api/filing/resort-plan").json()["calls"] == 2
    outcome = client.post("/api/filing/resort").json()
    assert outcome["notes"] == 30 and outcome["calls"] == 2
    assert [len(notes_in(p)) for p in prompts] == [25, 5]
    assert all(len(p) <= 12_000 for p in prompts)
    assert insight(client, mine)["effective_topic_id"] == topic_id(client, "Watch, read & listen")  # yours stays


def test_resort_retires_the_old_catch_all(client):
    database = sys.modules["app.database"]
    owner = (client.get("/api/auth/me").json().get("user") or client.get("/api/auth/me").json())["id"]
    with database.SessionLocal() as session:
        legacy = database.TopicRecord(name="Personal / Reference", description="Everything else", owner_user_id=owner,
                                      created_at="2026-11-01", updated_at="2026-11-01", archived=0, bot_key=None, origin="built_in")
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
    sorted_note = save(client, "Pay the electricity bill")
    unclear = save(client, "Remember the thing Aditi said")
    for note in (sorted_note, unclear):
        file(client, note)
        with database.SessionLocal() as session:
            row = session.get(database.ItemInsightRecord, note["id"])
            row.topic_id, row.filing_pending = legacy_id, 0
            session.commit()
    outcome = client.post("/api/filing/resort").json()
    assert outcome["retired_catch_all"] is True and outcome["waiting"] == 1
    assert "Personal / Reference" not in {t["name"] for t in client.get("/api/topics").json()}
    assert insight(client, sorted_note)["effective_topic_id"] == topic_id(client, "Bills & subscriptions")
    assert insight(client, unclear)["filing_pending"] is True  # unclear: it asks you


def test_a_new_topic_rechecks_only_likely_notes_and_can_be_undone(client):
    quiz = save(client, "Python quiz on Friday")
    loops = save(client, "Practise python loops tonight")
    milk = save(client, "Buy milk")
    pottery = save(client, "Self-directed learning about pottery glazes")  # shares only "learning"
    for note in (quiz, loops, milk, pottery):
        file(client, note)
    study = topic_id(client, "Study")
    before = {note["id"]: insight(client, note)["effective_topic_id"] for note in (quiz, loops, milk)}
    topic = client.post("/api/topics", json={"name": "Python", "description": "Learning Python", "parent_topic_id": study}).json()
    result = client.post(f"/api/topics/{topic['id']}/recheck").json()
    moved = {m["item_id"] for m in result["moved"]}
    assert moved == {quiz["id"], loops["id"]} and result["calls"] == 0  # offline: no AI call
    assert insight(client, milk)["effective_topic_id"] == before[milk["id"]]
    # One shared description word ("Learning Python") isn't a fit; it still waits for your pick.
    assert insight(client, pottery)["filing_pending"] is True
    assert all(insight(client, note)["effective_topic_id"] == topic["id"] for note in (quiz, loops))
    undone = client.post("/api/filing/undo-moves", json={"moves": result["moved"]}).json()
    assert undone == {"restored": 2}
    assert all(insight(client, note)["effective_topic_id"] == before[note["id"]] for note in (quiz, loops))
    # Nothing fits a topic about something else: no call at all.
    other = client.post("/api/topics", json={"name": "Origami", "description": "Paper folding"}).json()
    assert client.post(f"/api/topics/{other['id']}/recheck").json() == {
        "topic": {"id": other["id"], "name": "Origami"}, "moved": [], "calls": 0}


def test_deleting_a_topic_sends_unclear_notes_to_needs_you(client):
    gizmos = client.post("/api/topics", json={"name": "Gizmos", "description": "Gadgets and gizmos"}).json()
    note = save(client, "That gizmo Aditi mentioned")
    file(client, note)
    client.patch(f"/api/items/{note['id']}/insight", json={"user_topic_id": gizmos["id"]})
    response = client.delete(f"/api/topics/{gizmos['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["moved_notes"] == [{"item_id": note["id"], "topic_id": None, "topic_name": "Needs you"}]
    got = insight(client, note)
    assert got["filing_pending"] is True and got["effective_topic_id"] is None
    assert "Personal / Reference" not in {t["name"] for t in client.get("/api/topics").json()}
    assert any(c["kind"] == "area" and c["item_id"] == note["id"] for c in client.get("/api/captain/needs-you").json()["cards"])


# --- migration 0023 ------------------------------------------------------------------------


def test_migration_0023_records_who_filed_each_note(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "v22.db"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0022_captain_answers")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO analysis_runs (id, started_at, status, mode) VALUES "
                                "(1, '2026-11-01', 'succeeded', 'nvidia_nim'), (2, '2026-11-02', 'succeeded', 'fallback_no_api_call')"))
        for item_id in (1, 2, 3):
            connection.execute(text("INSERT INTO inbox_items (id, item_type, processing_status, created_at) "
                                    f"VALUES ({item_id}, 'text', 'ready', '2026-11-01')"))
        connection.execute(text(
            "INSERT INTO item_insights (item_id, analysis_run_id, category, concise_title, priority, needs_review, updated_at, user_topic_id) VALUES "
            "(1, 1, 'Study', 'A', 'Low', 0, 'x', NULL), (2, 2, 'Study', 'B', 'Low', 0, 'x', NULL), (3, 1, 'Study', 'C', 'Low', 0, 'x', 5)"))
    command.upgrade(config, "0023_filing_v2")
    try:
        with engine.begin() as connection:
            rows = connection.execute(text("SELECT item_id, filed_by, filing_pending FROM item_insights ORDER BY item_id")).all()
        assert [tuple(row) for row in rows] == [(1, "ai", 0), (2, "offline", 0), (3, "you", 0)]
    finally:
        engine.dispose()
