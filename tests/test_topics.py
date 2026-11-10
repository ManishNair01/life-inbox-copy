"""Topics with descriptions, AI/offline subtopic suggestions, and topic-aware sorting."""

import importlib
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import login, register


MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'topics.db'}")
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


def topics_by_name(client):
    return {t["name"]: t for t in client.get("/api/topics").json()}


def add_note(client, text):
    item = client.post("/api/items", json={"raw_text": text})
    assert item.status_code == 200, item.text
    return item.json()


def effective_topic_id(client, item_id):
    insight = client.get(f"/api/items/{item_id}/insight").json()
    return insight["user_topic_id"] or insight["topic_id"]


# --- built-in topics ---------------------------------------------------------


def test_built_in_topics_have_descriptions(client):
    topics = topics_by_name(client)
    assert topics["Medicines & doctors"]["is_built_in"] is True
    assert topics["Medicines & doctors"]["bot_key"] == "health"
    assert "refills" in topics["Medicines & doctors"]["description"]
    assert all(t["description"] for t in topics.values())
    # Built-in topics are main topics, except the subtopic Hobbies › Cooking.
    assert topics["Cooking"]["parent_topic_id"] == topics["Hobbies"]["id"] and topics["Cooking"]["is_built_in"]
    assert all(t["parent_topic_id"] is None for name, t in topics.items() if name != "Cooking")


# --- step 1: suggestion ------------------------------------------------------


def test_offline_suggests_medicines_for_pill_reminder(client):
    response = client.post(
        "/api/topics/suggest-parent",
        json={"name": "Pill reminder", "description": "Daily medicines and refills"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "offline"
    assert body["suggested_parent"]["name"] == "Medicines & doctors"
    assert body["suggested_parent"]["id"] == topics_by_name(client)["Medicines & doctors"]["id"]
    # A subtopic always shares its parent's life area.
    assert body["suggested_bot"] == {"key": "health", "name": "Health"}
    assert "medicine" in body["reason"]
    # Suggesting never creates anything.
    assert "Pill reminder" not in topics_by_name(client)


def test_no_suggestion_when_nothing_fits(client):
    body = client.post(
        "/api/topics/suggest-parent",
        json={"name": "Quantum foam", "description": "Spacetime at tiny scales"},
    ).json()
    assert body["suggested_parent"] is None
    assert body["suggested_bot"] is None


def test_suggestion_rejects_duplicate_names(client):
    response = client.post(
        "/api/topics/suggest-parent", json={"name": "medicines & doctors", "description": "x"}
    )
    assert response.status_code == 409


def test_catch_all_and_subtopics_are_never_suggested_as_parents(client):
    health = topics_by_name(client)["Medicines & doctors"]
    client.post(
        "/api/topics",
        json={"name": "Medicines", "description": "pills", "parent_topic_id": health["id"]},
    )
    body = client.post(
        "/api/topics/suggest-parent",
        json={"name": "Vitamin schedule", "description": "vitamin pills each morning"},
    ).json()
    # "Medicines" is a subtopic, so the suggestion goes to its main topic.
    assert body["suggested_parent"]["name"] == "Medicines & doctors"


# --- step 2: create as subtopic or as separate topic -------------------------


def test_accepting_suggestion_creates_subtopic(client):
    health = topics_by_name(client)["Medicines & doctors"]
    created = client.post(
        "/api/topics",
        json={
            "name": "Pill reminder",
            "description": "Daily medicines and refills",
            "parent_topic_id": health["id"],
        },
    )
    assert created.status_code == 200
    assert created.json()["parent_topic_id"] == health["id"]
    assert topics_by_name(client)["Pill reminder"]["parent_topic_id"] == health["id"]
    assert created.json()["bot_key"] == "health"


def test_declining_suggestion_creates_separate_topic(client):
    created = client.post(
        "/api/topics",
        json={"name": "Pill reminder", "description": "Daily medicines and refills"},
    )
    assert created.status_code == 200
    assert created.json()["parent_topic_id"] is None


def test_only_one_level_of_subtopics(client):
    health = topics_by_name(client)["Medicines & doctors"]
    child = client.post(
        "/api/topics",
        json={"name": "Medicines", "description": "pills", "parent_topic_id": health["id"]},
    ).json()
    grandchild = client.post(
        "/api/topics",
        json={"name": "Antibiotics", "description": "courses", "parent_topic_id": child["id"]},
    )
    assert grandchild.status_code == 400
    assert "main topic" in grandchild.json()["detail"]


def test_catch_all_cannot_have_subtopics(client):
    # New accounts have no catch-all (change 014); an older account's keeps
    # refusing subtopics until it's retired.
    assert "Personal / Reference" not in topics_by_name(client)
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    owner = (me.get("user") or me)["id"]
    with database.SessionLocal() as session:
        legacy = database.TopicRecord(
            name="Personal / Reference", description="Everything else", owner_user_id=owner,
            created_at="2026-11-01", updated_at="2026-11-01", archived=0, bot_key=None, origin="built_in",
        )
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
    response = client.post(
        "/api/topics",
        json={"name": "Misc", "description": "x", "parent_topic_id": legacy_id},
    )
    assert response.status_code == 400


def test_cannot_nest_under_another_users_topic(client):
    other_health = topics_by_name(client)["Medicines & doctors"]["id"]
    client.post("/api/auth/logout")
    register(client, "second@example.com")
    response = client.post(
        "/api/topics",
        json={"name": "Pill reminder", "description": "x", "parent_topic_id": other_health},
    )
    assert response.status_code == 400
    assert "not found" in response.json()["detail"]


# --- sorting notes into the user's topics ------------------------------------


def test_offline_analysis_files_notes_into_most_specific_topic(client):
    health = topics_by_name(client)["Medicines & doctors"]
    client.post(
        "/api/topics",
        json={
            "name": "Pill reminder",
            "description": "Daily medicines, refills and dosage",
            "parent_topic_id": health["id"],
        },
    )
    client.post("/api/topics", json={"name": "Recipes", "description": "Dishes I want to cook"})
    refill = add_note(client, "Refill my medicines on Friday")
    recipe = add_note(client, "Try the butter chicken recipe someday")
    dentist = add_note(client, "Book a dentist appointment")

    assert client.post("/api/analyze").status_code == 200
    topics = topics_by_name(client)
    assert effective_topic_id(client, refill["id"]) == topics["Pill reminder"]["id"]
    assert effective_topic_id(client, recipe["id"]) == topics["Recipes"]["id"]
    assert effective_topic_id(client, dentist["id"]) == topics["Medicines & doctors"]["id"]
    # The parent counts its own note plus the one in its subtopic.
    assert topics["Medicines & doctors"]["item_count"] == 1
    assert topics["Medicines & doctors"]["total_item_count"] == 2
    assert topics["Pill reminder"]["total_item_count"] == 1


def filed(note_id, topic, **extra):
    """One note in a filing v2 answer (change 014)."""
    entry = {"id": note_id, "area": extra.pop("area", None), "topic": topic, "confidence": "high",
             "rule": "R5", "choices": [], "title": extra.pop("title", "Title"), "priority": "Low",
             "tags": [], "reason": "Test.", "tasks": [], "transcript": None, "summary": None, "action": None}
    entry.update(extra)
    return entry


def test_ai_bucket_names_match_topics_case_insensitively(client, monkeypatch):
    client.post("/api/topics", json={"name": "Recipes", "description": "Dishes"})
    recipes = topics_by_name(client)["Recipes"]
    note = add_note(client, "Butter chicken recipe")
    prompts = fake_openai(monkeypatch, [{"notes": [
        filed(note["id"], "recipes", area=recipes["bot_key"], title="Butter chicken")
    ]}])
    assert client.post(f"/api/analyze?item_id={note['id']}").status_code == 200
    # The filing call was given the user's topics...
    assert '"topic": "Recipes"' in prompts[0] and '"topic": "Medicines & doctors"' in prompts[0]
    # ...and "recipes" reused the existing topic instead of creating a duplicate.
    names = [t["name"] for t in client.get("/api/topics").json()]
    assert names.count("Recipes") == 1 and "recipes" not in names
    assert effective_topic_id(client, note["id"]) == recipes["id"]
    assert len(prompts) == 1  # no repair call needed


# --- AI paths (mocked; never calls a live API) -------------------------------


def fake_openai(monkeypatch, payloads):
    """Make openai.OpenAI return canned chat completions, recording prompts."""
    import openai

    prompts = []

    def create(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        content = payloads.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))]
        )

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake_client)
    return prompts


TOPICS = [
    {"id": 5, "name": "Medicines & doctors", "description": "Pills, doses, refills",
     "parent_topic_id": None, "bot_key": "health", "is_built_in": True, "archived": False},
    {"id": 9, "name": "Personal / Reference", "description": "Everything else",
     "parent_topic_id": None, "bot_key": None, "is_built_in": True, "archived": False},
    {"id": 20, "name": "Pill reminder", "description": "Daily medicines", "parent_topic_id": 5,
     "bot_key": "health", "is_built_in": False, "archived": False},
]


def test_ai_suggestion_uses_only_main_topics(monkeypatch):
    sys.modules.pop("app.organizer", None)
    organizer = importlib.import_module("app.organizer")
    prompts = fake_openai(monkeypatch, [
        {"parent": "Medicines & doctors", "area": "health", "reason": "Vitamins are medicines."}
    ])
    result = organizer.suggest_parent_topic("Vitamin plan", "vitamins", TOPICS)
    assert result == {
        "suggested_parent": {"id": 5, "name": "Medicines & doctors"},
        "suggested_bot": {"key": "health", "name": "Health"},
        "reason": "Vitamins are medicines.",
        "mode": "ai",
    }
    assert '"name": "Medicines & doctors"' in prompts[0]
    assert '"name": "Pill reminder"' not in prompts[0]
    assert '"name": "Personal / Reference"' not in prompts[0]
    # The same call also picks the life area, from the five.
    assert '"key": "health"' in prompts[0] and '"key": "fun"' in prompts[0]


def test_ai_suggestion_of_unknown_topic_falls_back_offline(monkeypatch):
    sys.modules.pop("app.organizer", None)
    organizer = importlib.import_module("app.organizer")
    fake_openai(monkeypatch, [{"parent": "Wellness", "reason": "made up"}])
    result = organizer.suggest_parent_topic("Pill reminder", "medicine refills", TOPICS)
    assert result["mode"] == "offline"
    assert result["suggested_parent"]["name"] == "Medicines & doctors"


def test_ai_null_answer_means_no_suggestion(monkeypatch):
    sys.modules.pop("app.organizer", None)
    organizer = importlib.import_module("app.organizer")
    fake_openai(monkeypatch, [{"parent": None, "reason": ""}])
    result = organizer.suggest_parent_topic("Recipes", "cooking", TOPICS)
    # No parent; with no area from the AI, the keyword rules pick one.
    assert result == {
        "suggested_parent": None,
        "suggested_bot": {"key": "fun", "name": "Fun & interests"},
        "reason": None,
        "mode": "ai",
    }


def test_analysis_prompt_lists_user_topics_with_subtopics(monkeypatch):
    sys.modules.pop("app.organizer", None)
    organizer = importlib.import_module("app.organizer")
    output = {
        "buckets": [{"name": "Pill reminder", "notes": [
            {"id": 1, "title": "Refill", "priority": "Medium"}
        ]}],
        "todos": [],
        "priority_view": {"High": [], "Medium": [{"id": 1, "title": "Refill"}], "Low": []},
    }
    prompts = fake_openai(monkeypatch, [output])
    result = organizer.analyze_inbox_with_openai(
        [{"id": 1, "text": "Refill medicines", "created_at": "2026-11-01"}],
        topics=TOPICS,
    )
    assert result["buckets"][0]["name"] == "Pill reminder"
    # Topics are sent as JSON so a name can't be confused with its description.
    assert (
        '{"name": "Medicines & doctors", "about": "Pills, doses, refills", "subtopics": '
        '[{"name": "Pill reminder", "about": "Daily medicines"}]}'
    ) in prompts[0]
    assert "never the" in prompts[0] and "MOST SPECIFIC" in prompts[0]
    assert "- Medicines & doctors: Pills" not in prompts[0]


# --- AI bucket names that don't exactly match a topic --------------------------


def test_ai_name_with_description_maps_to_existing_topic(client, monkeypatch):
    """Regression: "Ideas: Product, business..." used to create a new topic."""
    idea = add_note(client, "Build a habit tracker app")
    friend = add_note(client, "Call Rohan about his birthday")
    before = set(topics_by_name(client))
    prompts = fake_openai(monkeypatch, [{"notes": [
        filed(idea["id"], "Skills & projects: Self-directed learning, tutorials, tools to try, side projects, app and startup ideas.",
              area="learn", title="Habit tracker"),
        filed(friend["id"], "Friends & partner: Friends, boyfriend/girlfriend, catch-ups, people to call or message.",
              area="people", title="Call Rohan"),
    ]}])
    filing = sys.modules["app.filing"]
    me = client.get("/api/auth/me").json()
    database = sys.modules["app.database"]
    database.set_current_owner_id((me.get("user") or me)["id"])
    try:
        notes = [database.get_note_from_db(idea["id"]), database.get_note_from_db(friend["id"])]
        filing._file_and_save(notes, database.list_topics_from_db())
    finally:
        database.set_current_owner_id(None)
    topics = topics_by_name(client)
    assert set(topics) == before  # nothing new was created
    assert effective_topic_id(client, idea["id"]) == topics["Skills & projects"]["id"]
    assert effective_topic_id(client, friend["id"]) == topics["Friends & partner"]["id"]
    assert len(prompts) == 1  # the description was understood without a repair call


def test_ai_quoted_and_variant_names_mean_the_same_topic(client, monkeypatch):
    client.post("/api/topics", json={"name": "Recipes", "description": "Dishes"})
    recipes = topics_by_name(client)["Recipes"]
    one = add_note(client, "Butter chicken recipe")
    fake_openai(monkeypatch, [{"notes": [filed(one["id"], "“Recipes”", area=recipes["bot_key"])]}])
    assert client.post(f"/api/analyze?item_id={one['id']}").status_code == 200
    two = add_note(client, "Paneer tikka recipe")
    fake_openai(monkeypatch, [{"notes": [filed(two["id"], "recipes (subtopic of nothing)", area=recipes["bot_key"])]}])
    assert client.post(f"/api/analyze?item_id={two['id']}").status_code == 200
    names = [t["name"] for t in client.get("/api/topics").json()]
    assert names.count("Recipes") == 1
    assert effective_topic_id(client, one["id"]) == effective_topic_id(client, two["id"]) == recipes["id"]


def test_the_ai_can_never_invent_a_topic(client, monkeypatch):
    # P1: filing only picks existing topics. An invented one fails code's
    # check, gets one repair call, and then the offline matcher files it.
    note = add_note(client, "Practice guitar chords")
    invented = {"notes": [filed(note["id"], "Music practice", area="fun", title="Guitar")]}
    prompts = fake_openai(monkeypatch, [invented, invented])
    assert client.post(f"/api/analyze?item_id={note['id']}").status_code == 200
    topics = topics_by_name(client)
    assert "Music practice" not in topics
    assert len(prompts) == 2 and "Music practice" in prompts[1] and "doesn't exist" in prompts[1]
    assert effective_topic_id(client, note["id"]) == topics["Hobbies"]["id"]
    insight = client.get(f"/api/items/{note['id']}/insight").json()
    assert insight["filed_by"] == "offline"


# --- topics are private to each account --------------------------------------


def test_custom_topics_are_private_to_their_owner(client, monkeypatch):
    client.post("/api/topics", json={"name": "Alice secret topic", "description": "mine"})
    assert "Alice secret topic" in topics_by_name(client)

    client.post("/api/auth/logout")
    register(client, "bob@example.com")
    # Not in Bob's topic list or his dashboard...
    assert "Alice secret topic" not in topics_by_name(client)
    dashboard_topics = {t["name"] for t in client.get("/api/dashboard").json()["topics"]}
    assert "Alice secret topic" not in dashboard_topics
    # ...and never sent to the AI when Bob's notes are filed.
    bobs = add_note(client, "Buy milk")
    prompts = fake_openai(monkeypatch, [{"notes": [filed(bobs["id"], "Home & errands", area="money")]}])
    client.post(f"/api/analyze?item_id={bobs['id']}")
    assert prompts and "Alice secret topic" not in prompts[0]
    # Bob can create a topic with the same name independently.
    assert client.post("/api/topics", json={"name": "Alice secret topic", "description": "bob's"}).status_code == 200

    client.post("/api/auth/logout")
    login(client, "owner@example.com")
    assert topics_by_name(client)["Alice secret topic"]["description"] == "mine"


# --- deleting topics ---------------------------------------------------------


def make_subtopic(client, name, description, parent_name):
    parent = topics_by_name(client)[parent_name]
    created = client.post(
        "/api/topics",
        json={"name": name, "description": description, "parent_topic_id": parent["id"]},
    )
    assert created.status_code == 200, created.text
    return created.json()


def test_deleting_subtopic_moves_notes_to_parent(client):
    pill = make_subtopic(client, "Pill reminder", "Daily medicines and refills", "Medicines & doctors")
    refill = add_note(client, "Refill my medicines on Friday")
    chosen = add_note(client, "Note I filed here myself")
    client.post("/api/analyze")
    assert effective_topic_id(client, refill["id"]) == pill["id"]
    # The user files a second note into the subtopic by hand.
    override = client.patch(
        f"/api/items/{chosen['id']}/insight", json={"user_topic_id": pill["id"]}
    )
    assert override.status_code == 200

    response = client.delete(f"/api/topics/{pill['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    health = topics_by_name(client)["Medicines & doctors"]
    assert body["deleted"] == {"id": pill["id"], "name": "Pill reminder"}
    assert body["moved_to_parent"] == {"id": health["id"], "name": "Medicines & doctors"}
    assert body["mode"] == "parent"
    assert {n["item_id"] for n in body["moved_notes"]} == {refill["id"], chosen["id"]}

    assert "Pill reminder" not in topics_by_name(client)
    assert effective_topic_id(client, refill["id"]) == health["id"]
    # The user's own choice is kept, one level up.
    assert client.get(f"/api/items/{chosen['id']}/insight").json()["user_topic_id"] == health["id"]
    assert topics_by_name(client)["Medicines & doctors"]["item_count"] == 2


def test_deleting_main_topic_resorts_notes_into_existing_topics(client):
    client.post("/api/topics", json={"name": "Recipes", "description": "Dishes I want to cook"})
    recipe = add_note(client, "Try the butter chicken recipe someday")
    medicine = add_note(client, "Recipe note: buy medicine for mom")
    client.post("/api/analyze")
    recipes = topics_by_name(client)["Recipes"]
    assert effective_topic_id(client, recipe["id"]) == recipes["id"]

    response = client.delete(f"/api/topics/{recipes['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["moved_to_parent"] is None
    assert body["mode"] == "offline"
    topics = topics_by_name(client)
    assert "Recipes" not in topics
    moved = {n["item_id"]: n["topic_name"] for n in body["moved_notes"]}
    # Every note lands in a topic that already existed.
    assert set(moved.values()) <= set(topics)
    assert moved[recipe["id"]] == "Cooking"
    # Rule R1 (change 014) filed the medicine note under Health from the
    # start, so deleting Recipes didn't touch it.
    assert medicine["id"] not in moved
    assert effective_topic_id(client, medicine["id"]) == topics["Medicines & doctors"]["id"]
    assert effective_topic_id(client, recipe["id"]) == topics["Cooking"]["id"]


def test_deleting_main_topic_promotes_its_subtopics(client):
    client.post("/api/topics", json={"name": "Baking", "description": "Food and kitchen"})
    desserts = make_subtopic(client, "Desserts", "Cakes and sweets", "Baking")
    cake = add_note(client, "Bake a chocolate cake with sweets on top")
    client.post("/api/analyze")
    assert effective_topic_id(client, cake["id"]) == desserts["id"]

    cooking = topics_by_name(client)["Baking"]
    body = client.delete(f"/api/topics/{cooking['id']}").json()
    assert body["promoted_subtopics"] == [{"id": desserts["id"], "name": "Desserts"}]
    topics = topics_by_name(client)
    assert topics["Desserts"]["parent_topic_id"] is None
    # Notes already in the subtopic stay there.
    assert effective_topic_id(client, cake["id"]) == desserts["id"]


def test_deleted_topic_disappears_from_latest_analysis(client):
    client.post("/api/topics", json={"name": "Recipes", "description": "Dishes I want to cook"})
    recipe = add_note(client, "Try the butter chicken recipe someday")
    client.post("/api/analyze")
    names = [b["name"] for b in client.get("/api/analyze/latest").json()["buckets"]]
    assert "Recipes" in names

    client.delete(f"/api/topics/{topics_by_name(client)['Recipes']['id']}")
    latest = client.get("/api/analyze/latest").json()
    by_bucket = {b["name"]: [n["id"] for n in b["notes"]] for b in latest["buckets"]}
    assert "Recipes" not in by_bucket
    assert recipe["id"] in by_bucket["Cooking"]


def test_deleting_topic_without_notes(client):
    created = client.post("/api/topics", json={"name": "Empty", "description": "Nothing yet"}).json()
    body = client.delete(f"/api/topics/{created['id']}").json()
    assert body["moved_notes"] == [] and body["mode"] == "none"
    assert "Empty" not in topics_by_name(client)


def test_built_in_topics_cannot_be_deleted(client):
    health = topics_by_name(client)["Medicines & doctors"]
    response = client.delete(f"/api/topics/{health['id']}")
    assert response.status_code == 400
    assert "Built-in" in response.json()["detail"]
    assert "Medicines & doctors" in topics_by_name(client)


def test_cannot_delete_another_users_topic(client):
    created = client.post("/api/topics", json={"name": "Private", "description": "mine"}).json()
    client.post("/api/auth/logout")
    register(client, "second@example.com")
    assert client.delete(f"/api/topics/{created['id']}").status_code == 404
    assert client.delete("/api/topics/999999").status_code == 404
    client.post("/api/auth/logout")
    login(client, "owner@example.com")
    assert "Private" in topics_by_name(client)


def test_note_cannot_be_moved_to_another_users_topic(client):
    """Security fix: a note's topic override must be one of the owner's topics."""
    other_topic = client.post("/api/topics", json={"name": "Owner only", "description": "x"}).json()
    client.post("/api/auth/logout")
    register(client, "second@example.com")
    note = add_note(client, "Second user's note")
    client.post("/api/analyze")
    response = client.patch(
        f"/api/items/{note['id']}/insight", json={"user_topic_id": other_topic["id"]}
    )
    assert response.status_code == 400


def test_ai_reassignment_only_uses_existing_topics(monkeypatch):
    sys.modules.pop("app.organizer", None)
    organizer = importlib.import_module("app.organizer")
    prompts = fake_openai(monkeypatch, [{"assignments": [
        {"id": 1, "topic": "medicines & doctors"},
        {"id": 2, "topic": "Brand New Topic"},
        {"id": 99, "topic": "Medicines & doctors"},
    ]}])
    result = organizer.reassign_notes_to_topics(
        [{"id": 1, "text": "Refill medicines"}, {"id": 2, "text": "Something random"}],
        TOPICS,
    )
    assert result["mode"] == "ai"
    assert result["assignments"][1] == "Medicines & doctors"
    # A made-up topic is ignored; nothing fits "Something random", so it gets
    # no topic and waits in Needs you (change 014: never the catch-all).
    assert result["assignments"][2] is None
    assert 99 not in result["assignments"]
    assert "Do NOT invent new" in prompts[0]
    assert '"name": "Pill reminder"' in prompts[0]


def test_offline_reassignment_prefers_user_subtopics():
    sys.modules.pop("app.organizer", None)
    organizer = importlib.import_module("app.organizer")
    result = organizer.reassign_notes_to_topics(
        [{"id": 1, "text": "Refill daily medicines"}], TOPICS
    )
    assert result == {"assignments": {1: "Pill reminder"}, "mode": "offline"}
