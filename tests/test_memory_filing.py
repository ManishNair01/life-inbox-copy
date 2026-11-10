"""Change 017: memory in filing (the AI is always faked).

Memory is off unless LIFE_INBOX_MEMORY_IN_FILING=1. When on, the filing call
gets "What Life Inbox knows" (plans, core profile, a shortlist of confirmed
facts) within its size cap; the answer's "memory_used" is checked and saved;
a "plan_update" waits in Needs you until you say Yes or "a different one"."""

import importlib
import json
import sys
from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register
from tests.test_filing import entry, notes_in

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")
KNOWS = "What Life Inbox knows about the user"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'memory_filing.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("LIFE_INBOX_TIMEZONE", raising=False)
    monkeypatch.setenv("LIFE_INBOX_MEMORY_IN_FILING", "1")
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


def save(client, text):
    response = client.post("/api/items", json={"raw_text": text})
    assert response.status_code == 200, response.text
    return response.json()


def file(client, note):
    response = client.post("/api/analyze", params={"item_id": note["id"]})
    assert response.status_code == 200, response.text
    return response.json()


def as_owner(client):
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    return database


def today():
    from app.attention.dates import today_in_configured_tz

    return today_in_configured_tz()


def pack_in(prompt):
    """The "What Life Inbox knows" JSON of a filing prompt, or None."""
    if KNOWS not in prompt:
        return None
    return json.loads(prompt.split(KNOWS, 1)[1].split("\n", 2)[1])


def fake_ai(monkeypatch, decide, prompts):
    import openai

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        prompts.append(prompt)
        answer = {"notes": [decide(note, prompt) for note in notes_in(prompt)]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


def dated_task(client, text, days, time=None):
    task = client.post("/api/tasks", json={"text": text}).json()
    body = {"due_on": (today() + timedelta(days=days)).isoformat(), **({"due_time": time} if time else {})}
    response = client.post(f"/api/tasks/{task['id']}/date", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def calls():
    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        return [row.outcome for row in session.query(database.AiCallRecord).filter_by(action="filing")]


# --- off by default ----------------------------------------------------------------------


def test_memory_stays_out_of_the_prompt_unless_switched_on(client, monkeypatch):
    database = as_owner(client)
    database.remember("You run your college's events", kind="long_term", source_kind="you", status="confirmed")
    prompts = []
    fake_ai(monkeypatch, lambda note, _p: entry(note["id"], "Work & career", "learn"), prompts)
    monkeypatch.delenv("LIFE_INBOX_MEMORY_IN_FILING")
    file(client, save(client, "Book the auditorium for the college fest"))
    assert prompts and KNOWS not in prompts[-1]
    assert '"memory_used"' not in prompts[-1] and '"plan_update"' not in prompts[-1]


# --- the pack ------------------------------------------------------------------------------


def test_the_pack_holds_plans_core_facts_and_relevant_confirmed_hints(client, monkeypatch):
    database = as_owner(client)
    dentist = dated_task(client, "Dentist appointment", 3, "10:00")
    events = database.remember("You run your college's events", kind="long_term", source_kind="you", status="confirmed")
    core = database.remember("You are a final-year student", kind="long_term", source_kind="onboarding",
                             status="confirmed", core=True)
    database.remember("You play chess on weekends", kind="long_term", source_kind="you", status="confirmed")
    unconfirmed = database.remember("You manage the college fest budget", kind="long_term", source_kind="your_words")
    prompts = []
    fake_ai(monkeypatch, lambda note, _p: entry(note["id"], "Work & career", "learn"), prompts)
    file(client, save(client, "Book the auditorium for the college events week"))

    pack = pack_in(prompts[-1])
    assert pack["coming_up"] == [{"id": f"p{dentist['id']}", "task": "Dentist appointment",
                                  "day": dentist["due_on"], "time": "10:00"}]
    assert pack["about_you"] == [{"id": f"m{core['id']}", "fact": "You are a final-year student"}]
    hint_ids = [hint["id"] for hint in pack["hints"]]
    assert hint_ids[0] == f"m{events['id']}"  # shares "college" and "events"
    assert f"m{unconfirmed['id']}" not in hint_ids  # only confirmed facts go to the AI
    assert "hint only" in prompts[-1] or "hints only" in prompts[-1]


def test_the_pack_stays_within_its_size_cap(client, monkeypatch):
    database = as_owner(client)
    for number in range(40):
        database.remember(f"You keep notes about college project number {number} with a long description "
                          f"of its goals, its members and its deadlines, version {number}",
                          kind="long_term", source_kind="you", status="confirmed")
    prompts = []
    fake_ai(monkeypatch, lambda note, _p: entry(note["id"], "Work & career", "learn"), prompts)
    file(client, save(client, "College project deadlines and members"))
    pack = pack_in(prompts[-1])
    assert 0 < len(pack["hints"]) <= 15
    assert len(json.dumps(pack, ensure_ascii=False)) <= 1_800
    assert len(prompts[-1]) <= 12_000


def test_health_facts_reach_the_pack_only_with_consent(client, monkeypatch):
    database = as_owner(client)
    prompts = []
    fake_ai(monkeypatch, lambda note, _p: entry(note["id"], "Medicines & doctors", "health"), prompts)
    client.patch("/api/settings", json={"health_memory_consent": True})
    database.remember("Your mother takes thyroid tablets", kind="long_term", source_kind="you", status="confirmed")
    file(client, save(client, "Refill the thyroid tablets"))
    assert "thyroid tablets" in json.dumps(pack_in(prompts[-1]))
    client.patch("/api/settings", json={"health_memory_consent": False})
    file(client, save(client, "Refill the thyroid tablets again"))
    assert "Your mother" not in prompts[-1]


# --- the answer ----------------------------------------------------------------------------


def test_memory_used_is_checked_saved_and_shown(client, monkeypatch):
    database = as_owner(client)
    events = database.remember("You run your college's events", kind="long_term", source_kind="you", status="confirmed")
    prompts = []
    fake_ai(monkeypatch, lambda note, _p: entry(note["id"], "Work & career", "learn",
                                                memory_used=[f"m{events['id']}", "m9999", "p1"]), prompts)
    note = save(client, "Finalise the stall list for the college events by Thursday")
    file(client, note)
    insight = client.get(f"/api/items/{note['id']}/insight").json()
    assert insight["memory_used"] == [{"id": f"m{events['id']}", "text": "You run your college's events"}]
    assert calls() == ["ok"]  # an unknown hint id is dropped, never a repair call


def test_a_note_that_moves_a_plan_asks_first(client, monkeypatch):
    dentist = dated_task(client, "Dentist appointment", 3, "10:00")
    new_day = (today() + timedelta(days=5)).isoformat()
    prompts = []

    def decide(note, prompt):
        plan = pack_in(prompt)["coming_up"][0]["id"]
        return entry(note["id"], "Medicines & doctors", "health",
                     tasks=[{"task": "Dentist appointment", "intent": "commitment", "when": "Friday 4pm",
                             "date": new_day, "time": "16:00"}],
                     plan_update={"plan": plan, "date": new_day, "time": "16:00"})

    fake_ai(monkeypatch, decide, prompts)
    note = save(client, "Dentist moved to Friday 4pm")
    file(client, note)

    tasks = client.get("/api/tasks?status=open").json()
    assert [task["text"] for task in tasks] == ["Dentist appointment"]  # no second dentist task
    assert tasks[0]["due_on"] == dentist["due_on"]  # nothing moves until you say
    needs = client.get("/api/captain/needs-you").json()["cards"]
    [card] = [card for card in needs if card["kind"] == "plan"]
    assert card["heading"] == "Did a plan move?"
    assert "Move it?" in card["text"] and "16:00" in card["text"]
    assert [action["action"] for action in card["actions"]] == ["move", "different"]

    response = client.post(f"/api/captain/needs-you/{card['id']}/resolve", json={"action": "move"})
    assert response.status_code == 200, response.text
    [task] = client.get("/api/tasks?status=open").json()
    assert (task["due_on"], task["due_time"], task["timing_confirmed"]) == (new_day, "16:00", True)
    assert note["id"] in task["source_item_ids"]
    assert all(card["kind"] != "plan" for card in client.get("/api/captain/needs-you").json()["cards"])


def test_a_different_one_gets_its_own_task(client, monkeypatch):
    dated_task(client, "Team lunch", 2)
    new_day = (today() + timedelta(days=4)).isoformat()
    prompts = []
    fake_ai(monkeypatch, lambda note, prompt: entry(
        note["id"], "Friends & partner", "people",
        tasks=[{"task": "Team lunch with Aman", "intent": "commitment", "when": None, "date": new_day, "time": None}],
        plan_update={"plan": pack_in(prompt)["coming_up"][0]["id"], "date": new_day, "time": None}), prompts)
    file(client, save(client, "Team lunch with Aman on Saturday"))
    [card] = [card for card in client.get("/api/captain/needs-you").json()["cards"] if card["kind"] == "plan"]
    client.post(f"/api/captain/needs-you/{card['id']}/resolve", json={"action": "different"})
    tasks = sorted(client.get("/api/tasks?status=open").json(), key=lambda task: task["id"])
    assert [task["text"] for task in tasks] == ["Team lunch", "Team lunch with Aman"]
    assert tasks[1]["suggested_due_on"] == new_day or tasks[1]["due_on"] == new_day


def test_a_bad_plan_update_is_ignored_without_a_repair_call(client, monkeypatch):
    dentist = dated_task(client, "Dentist appointment", 3)
    prompts = []
    fake_ai(monkeypatch, lambda note, _p: entry(note["id"], "Medicines & doctors", "health",
                                                plan_update={"plan": "p9999", "date": "2026-02-31"}), prompts)
    file(client, save(client, "Dentist again sometime"))
    assert calls() == ["ok"]
    assert all(card["kind"] != "plan" for card in client.get("/api/captain/needs-you").json()["cards"])
    assert client.get(f"/api/tasks?status=open").json()[0]["due_on"] == dentist["due_on"]


def test_resorting_never_sends_memory(client, monkeypatch):
    database = as_owner(client)
    database.remember("You run your college's events", kind="long_term", source_kind="you", status="confirmed")
    filing = importlib.import_module("app.filing")
    notes = [{"id": 1, "text": "College events budget"}]
    prompt = filing.build_prompt(notes, database.list_topics_from_db(), compact=True)
    assert KNOWS not in prompt


# --- the replay harness ----------------------------------------------------------------------


def test_the_replay_harness_never_runs_without_live_and_never_uses_the_real_database(tmp_path):
    import subprocess

    from scripts import memory_replay

    assert memory_replay.SCENARIOS and all(s["note"] and s["expect"] for s in memory_replay.SCENARIOS)
    assert "life_inbox.db" not in memory_replay.replay_database_url(tmp_path)
    completed = subprocess.run([sys.executable, "-m", "scripts.memory_replay"], capture_output=True, text=True,
                               cwd=str(importlib.import_module("pathlib").Path(__file__).resolve().parent.parent))
    assert completed.returncode == 2
    assert "--live" in completed.stdout + completed.stderr
