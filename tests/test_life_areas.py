"""The five life areas (change 008): defaults, GET /api/bots, the ?bot= lens,
topic areas, and migration 0018 from a v1 database."""

import importlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIVE = ["learn", "money", "health", "people", "fun"]
DEFAULTS = {
    "learn": {"Study", "Work & career", "Skills & projects"},
    "money": {"Bills & subscriptions", "Bank, tax & documents", "Home & errands"},
    "health": {"Medicines & doctors", "Fitness & food", "Mind & mood"},
    "people": {"Family", "Friends & partner", "Occasions & gifts"},
    "fun": {"Watch, read & listen", "Hobbies", "Cooking", "Trips & places"},
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'areas.db'}")
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


def topics_by_name(client, **params):
    return {t["name"]: t for t in client.get("/api/topics", params=params).json()}


def add_and_file(client, *texts):
    items = [client.post("/api/items", json={"raw_text": t}).json() for t in texts]
    assert client.post("/api/analyze").status_code == 200
    return items


# --- defaults for a new account -------------------------------------------------


def test_new_account_gets_five_areas_with_three_topics_each(client):
    topics = topics_by_name(client)
    for bot, names in DEFAULTS.items():
        in_area = {name for name, t in topics.items() if t["bot_key"] == bot}
        assert in_area == names
    for name in set().union(*DEFAULTS.values()):
        assert topics[name]["origin"] == "built_in" and topics[name]["is_built_in"]
        assert topics[name]["description"]
    # No catch-all for a new account (change 014): unclear notes wait in Needs you.
    assert "Personal / Reference" not in topics
    assert len(topics) == 16  # 15 main topics + Hobbies › Cooking


def test_list_of_bots(client):
    bots = client.get("/api/bots").json()
    assert [b["key"] for b in bots] == FIVE
    assert [b["name"] for b in bots] == [
        "Learning & work", "Money & home", "Health", "People", "Fun & interests",
    ]
    for bot in bots:
        # Three main topics each; Fun & interests also has the subtopic Hobbies › Cooking.
        assert bot["topic_count"] == (4 if bot["key"] == "fun" else 3)
        assert (bot["item_count"], bot["open_task_count"]) == (0, 0)
        assert bot["status"] == "Nothing yet" and bot["next_task"] is None


def test_bot_status_shows_the_next_dated_task(client):
    from app.attention.dates import today_in_configured_tz

    add_and_file(client, "Read the lecture notes tomorrow", "Book a dentist appointment")
    bots = {b["key"]: b for b in client.get("/api/bots").json()}
    learn = bots["learn"]
    tomorrow = (today_in_configured_tz() + timedelta(days=1)).isoformat()
    assert learn["item_count"] == 1 and learn["open_task_count"] == 1
    assert learn["next_task"]["due_on"] == tomorrow
    assert learn["status"].startswith("Read the lecture notes tomorrow · ")
    assert bots["health"]["item_count"] == 1
    assert bots["health"]["status"] in {"1 note", "1 open task, no dates"}
    assert bots["fun"]["status"] == "Nothing yet"


def test_bots_only_count_your_own_notes(client):
    add_and_file(client, "Book a dentist appointment")
    client.post("/api/auth/logout")
    register(client, "second@example.com")
    assert all(b["item_count"] == 0 for b in client.get("/api/bots").json())


# --- the lens: ?bot= ---------------------------------------------------------------


def test_lists_filter_by_life_area(client):
    from app.attention.dates import today_in_configured_tz

    study, dentist = add_and_file(client, "Read the lecture notes tomorrow", "Book a dentist appointment")

    def ids(path, **params):
        return [row["id"] for row in client.get(path, params=params).json()]

    assert ids("/api/items", bot="learn") == [study["id"]]
    assert ids("/api/items", bot="health") == [dentist["id"]]
    assert ids("/api/items", bot="fun") == []
    assert len(ids("/api/items")) == 2  # no lens: everything

    learn_tasks = client.get("/api/tasks", params={"bot": "learn"}).json()
    assert learn_tasks and all(study["id"] in t["source_item_ids"] for t in learn_tasks)
    assert client.get("/api/tasks", params={"bot": "fun"}).json() == []

    assert set(topics_by_name(client, bot="health")) == DEFAULTS["health"]

    hits = client.get("/api/search", params={"q": "dentist", "bot": "health"}).json()
    assert [h["item_id"] for h in hits] == [dentist["id"]]
    assert client.get("/api/search", params={"q": "dentist", "bot": "learn"}).json() == []

    today = today_in_configured_tz()
    window = {"start": today.isoformat(), "end": (today + timedelta(days=7)).isoformat()}
    learn_events = client.get("/api/calendar/events", params={**window, "bot": "learn"}).json()
    assert [e["source_item_id"] for e in learn_events] == [study["id"]]
    assert client.get("/api/calendar/events", params={**window, "bot": "health"}).json() == []


def test_unknown_life_area_is_rejected(client):
    for path, params in (
        ("/api/items", {}), ("/api/tasks", {}), ("/api/topics", {}),
        ("/api/search", {"q": "x"}),
        ("/api/calendar/events", {"start": "2026-11-01", "end": "2026-11-30"}),
    ):
        response = client.get(path, params={**params, "bot": "travel"})
        assert response.status_code == 422, path
        assert "learn" in response.json()["detail"]


def test_your_pick_decides_the_area(client):
    """A note you move by hand follows your choice, not the AI's."""
    (dentist,) = add_and_file(client, "Book a dentist appointment")
    trips = topics_by_name(client)["Trips & places"]
    client.patch(f"/api/items/{dentist['id']}/insight", json={"user_topic_id": trips["id"]})
    assert [i["id"] for i in client.get("/api/items", params={"bot": "fun"}).json()] == [dentist["id"]]
    assert client.get("/api/items", params={"bot": "health"}).json() == []


# --- topics and their areas ----------------------------------------------------------


def create(client, **body):
    return client.post("/api/topics", json={"description": "", **body})


def test_new_topic_gets_an_area(client):
    gym = create(client, name="Gym plan", description="Leg day and cardio")
    assert gym.status_code == 200 and gym.json()["bot_key"] == "health"
    chosen = create(client, name="Board games", bot_key="fun")
    assert chosen.json()["bot_key"] == "fun" and chosen.json()["origin"] == "user"
    hobby = create(client, name="Chess openings", description="Moves to practise")
    assert hobby.json()["bot_key"] == "fun"  # chess is a hobby
    unknown = create(client, name="Quantum foam", description="Spacetime at tiny scales")
    assert unknown.json()["bot_key"] is None  # Captain will ask (change 013)
    assert create(client, name="Puzzles", bot_key="travel").status_code == 422


def test_subtopic_shares_its_parents_area(client):
    study = topics_by_name(client)["Study"]
    python = create(client, name="Python", description="Learning Python", parent_topic_id=study["id"])
    assert python.json()["bot_key"] == "learn"
    clash = create(client, name="Statistics", parent_topic_id=study["id"], bot_key="fun")
    assert clash.status_code == 400
    assert "parent" in clash.json()["detail"]


def test_moving_a_topic_moves_its_subtopics(client):
    hobby = create(client, name="Chess", description="Openings", bot_key="fun").json()
    child = create(client, name="Endgames", parent_topic_id=hobby["id"]).json()
    assert child["bot_key"] == "fun"
    moved = client.patch(f"/api/topics/{hobby['id']}", json={"bot_key": "learn"})
    assert moved.status_code == 200 and moved.json()["bot_key"] == "learn"
    assert topics_by_name(client)["Endgames"]["bot_key"] == "learn"


def test_moving_rules(client):
    topics = topics_by_name(client)
    built_in = client.patch(f"/api/topics/{topics['Study']['id']}", json={"bot_key": "fun"})
    assert built_in.status_code == 400
    parent = create(client, name="Chess", bot_key="fun").json()
    child = create(client, name="Endgames", parent_topic_id=parent["id"]).json()
    alone = client.patch(f"/api/topics/{child['id']}", json={"bot_key": "learn"})
    assert alone.status_code == 400 and "parent" in alone.json()["detail"]
    assert client.patch(f"/api/topics/{parent['id']}", json={"bot_key": "nope"}).status_code == 422


def test_renamed_built_in_topic_stays_built_in(client):
    study = topics_by_name(client)["Study"]
    renamed = client.patch(f"/api/topics/{study['id']}", json={"name": "College"}).json()
    assert renamed["is_built_in"] and renamed["bot_key"] == "learn"
    assert client.delete(f"/api/topics/{study['id']}").status_code == 400


def test_suggestion_includes_the_area(client):
    body = client.post(
        "/api/topics/suggest-parent",
        json={"name": "Recipes", "description": "Dishes I want to cook"},
    ).json()
    assert body["suggested_parent"]["name"] == "Hobbies"  # recipes go with Cooking, under Hobbies
    assert body["suggested_bot"] == {"key": "fun", "name": "Fun & interests"}


# --- migration 0018 from a v1 database ------------------------------------------------

V1 = {
    "Work": "Job, meetings, colleagues, projects, interviews and career.",
    "Money & Admin": "Bills, taxes, insurance, banking, paperwork and subscriptions.",
    "Learning": "Things to read, watch, study or look into; courses and articles.",
    "Shopping & Errands": "Things to buy, pick up, order or get done around town.",
    "Health": "Doctors, medicines, fitness, diet, sleep and wellbeing.",
    "Travel": "Trips, bookings, flights, hotels and places to visit.",
    "Ideas": "Product, business and creative ideas worth keeping.",
    "People": "Friends and family: calls, follow-ups, birthdays and favours.",
    "Personal / Reference": "Everything else worth remembering for later.",
}


def alembic_config(database_path):
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def test_migration_moves_v1_topics_onto_the_five_areas(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "v1.db"
    config = alembic_config(database_path)
    command.upgrade(config, "0017_ai_call_log")
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as db:
            for user_id in (101, 102, 103):
                db.execute(text(
                    "INSERT INTO users (id, email, display_name, auth_provider, created_at) "
                    "VALUES (:id, :email, '', 'password', '2026-11-01')"
                ), {"id": user_id, "email": f"u{user_id}@example.com"})

            def topic(owner, name, description, parent=None):
                return db.execute(text(
                    "INSERT INTO topics (name, description, owner_user_id, created_at, updated_at, "
                    "archived, parent_topic_id) VALUES (:n, :d, :o, '2026-11-01', '2026-11-01', 0, :p)"
                ), {"n": name, "d": description, "o": owner, "p": parent}).lastrowid

            ids = {name: topic(101, name, desc) for name, desc in V1.items()}
            # The user edited Travel's description; it must be kept.
            db.execute(text("UPDATE topics SET description = 'Only work trips' WHERE id = :id"),
                       {"id": ids["Travel"]})
            study = topic(101, "Study", "My study planner")  # same name as a new default
            python = topic(101, "Python", "I want to learn Python", ids["Learning"])
            pill = topic(101, "Pill reminder", "When to take my tablets", ids["Health"])
            gym = topic(101, "Gym plan", "Leg day and cardio")
            ai_topic = topic(101, "Ideas: Product, business", "Created from AI organization")
            family = topic(101, "Family", "My family stuff")
            for name, desc in V1.items():  # a second account with only the v1 defaults
                topic(102, name, desc)

            db.execute(text(
                "INSERT INTO inbox_items (id, item_type, raw_text, processing_status, created_at, owner_user_id) "
                "VALUES (1, 'text', 'Statistics practice', 'ready', '2026-11-01', 101), "
                "(2, 'text', 'Refill tablets', 'ready', '2026-11-01', 101), "
                "(3, 'text', 'Planner page', 'ready', '2026-11-01', 101)"
            ))
            buckets = {"buckets": [
                {"name": "Learning", "notes": [{"id": 1, "title": "Statistics", "priority": "Low"}]},
                {"name": "Study", "notes": [{"id": 3, "title": "Planner", "priority": "Low"}]},
            ], "todos": [], "priority_view": {"High": [], "Medium": [], "Low": []}}
            db.execute(text(
                "INSERT INTO analysis_runs (id, started_at, status, mode, owner_user_id, result_json) "
                "VALUES (1, '2026-11-01', 'succeeded', 'fallback', 101, :json)"
            ), {"json": json.dumps(buckets)})
            db.execute(text(
                "INSERT INTO item_insights (item_id, analysis_run_id, category, concise_title, priority, "
                "updated_at, topic_id, user_topic_id) VALUES "
                "(1, 1, 'Learning', 'Statistics', 'Low', '2026-11-01', :learning, NULL), "
                "(2, 1, 'Health', 'Refill', 'Low', '2026-11-01', :health, :pill), "
                "(3, 1, 'Study', 'Planner', 'Low', '2026-11-01', :study, NULL)"
            ), {"learning": ids["Learning"], "health": ids["Health"], "pill": pill, "study": study})

        command.upgrade(config, "head")

        with engine.connect() as db:
            def rows(owner):
                result = db.execute(text(
                    "SELECT id, name, description, bot_key, origin, parent_topic_id "
                    "FROM topics WHERE owner_user_id = :o"
                ), {"o": owner}).mappings()
                return {row["name"]: dict(row) for row in result}

            mine = rows(101)
            assert not set(mine) & {"Work", "Money & Admin", "Learning", "Shopping & Errands",
                                    "Health", "Travel", "Ideas", "People"}
            for bot, names in DEFAULTS.items():
                for name in names:
                    assert mine[name]["bot_key"] == bot and mine[name]["origin"] == "built_in", name
            assert mine["Personal / Reference"]["bot_key"] is None
            assert mine["Personal / Reference"]["origin"] == "built_in"

            # "Learning" was merged into the user's own "Study": notes, subtopics, view.
            assert mine["Study"]["id"] == study
            assert mine["Study"]["description"] == "My study planner"
            insight = {row[0]: row[1:] for row in db.execute(text(
                "SELECT item_id, topic_id, user_topic_id, category FROM item_insights"))}
            assert insight[1] == (study, None, "Study")
            assert mine["Python"]["parent_topic_id"] == study and mine["Python"]["bot_key"] == "learn"
            stored = json.loads(db.scalar(text("SELECT result_json FROM analysis_runs WHERE id = 1")))
            assert [(b["name"], [n["id"] for n in b["notes"]]) for b in stored["buckets"]] == [
                ("Study", [1, 3])
            ]

            # Renamed in place: same id, so every note stayed on its topic.
            assert mine["Medicines & doctors"]["id"] == ids["Health"]
            assert insight[2] == (ids["Health"], pill, "Medicines & doctors")
            assert mine["Pill reminder"]["parent_topic_id"] == ids["Health"]
            assert mine["Pill reminder"]["bot_key"] == "health"
            assert mine["Trips & places"]["description"] == "Only work trips"
            assert mine["Bills & subscriptions"]["description"].startswith("Anything you pay")

            # The user's own topics get an area and keep their origin.
            assert (mine["Gym plan"]["bot_key"], mine["Gym plan"]["origin"]) == ("health", "user")
            assert mine["Ideas: Product, business"]["origin"] == "ai"
            assert mine["Ideas: Product, business"]["bot_key"] == "learn"
            assert mine["Family"]["id"] == family and mine["Family"]["origin"] == "built_in"
            assert mine["Family"]["description"] == "My family stuff"
            assert mine["Family"]["bot_key"] == "people"
            assert len(mine) == 17 + 4  # defaults (incl. Hobbies › Cooking) + catch-all, plus Python, Pill reminder, Gym plan, AI topic
            assert {gym, ai_topic, python} <= {t["id"] for t in mine.values()}

            # A second account with only v1 defaults ends with exactly the new set.
            theirs = rows(102)
            assert set(theirs) == set().union(*DEFAULTS.values()) | {"Personal / Reference"}
            # An account with no topics yet gets them from the app on first use.
            assert rows(103) == {}
    finally:
        engine.dispose()
