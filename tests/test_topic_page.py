"""Topics and spaces and the topic page (change 010): a topic's notes
(subtopics included), the topic's detail with its kinds of notes, and renaming
without duplicates or stale names."""

import importlib
import json
import sys

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import login, register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'topic_page.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    # Never fetch the real internet in tests.
    monkeypatch.setattr(main, "fetch_url", lambda url: {
        "final_url": url,
        "title": "Python for beginners, full course",
        "raw_text": "A course on Python basics: variables, loops and functions.",
        "mime_type": "text/html",
        "status_code": 200,
    })
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com")
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def topics_by_name(client):
    return {t["name"]: t for t in client.get("/api/topics").json()}


def add_and_file(client, *texts):
    items = [client.post("/api/items", json={"raw_text": t}).json() for t in texts]
    assert client.post("/api/analyze").status_code == 200
    return items


def add_link(client):
    """A saved link, filed the way the composer files it (analysis right after)."""
    link = client.post("/api/items/url", json={"url": "https://example.com/python-course"}).json()
    assert client.post("/api/analyze", params={"item_id": link["id"]}).status_code == 200
    return link


def move(client, item, topic):
    response = client.patch(f"/api/items/{item['id']}/insight", json={"user_topic_id": topic["id"]})
    assert response.status_code == 200, response.text


def ids(client, **params):
    response = client.get("/api/items", params=params)
    assert response.status_code == 200, response.text
    return [row["id"] for row in response.json()]


@pytest.fixture()
def study_with_python(client):
    """Study with a Python subtopic: one note in each, and a note elsewhere."""
    study = topics_by_name(client)["Study"]
    python = client.post("/api/topics", json={
        "name": "Python", "description": "Learning Python", "parent_topic_id": study["id"],
    }).json()
    lecture, dentist, quiz = add_and_file(
        client, "Read the lecture notes tomorrow", "Book a dentist appointment", "Revise loops for Friday",
    )
    move(client, lecture, study)
    move(client, quiz, python)
    move(client, dentist, topics_by_name(client)["Medicines & doctors"])
    return {"study": study, "python": python, "lecture": lecture, "quiz": quiz, "dentist": dentist}


# --- a topic's notes ------------------------------------------------------------------


def test_a_topics_notes_include_its_subtopics(client, study_with_python):
    s = study_with_python
    assert ids(client, topic_id=s["study"]["id"], order="desc") == [s["quiz"]["id"], s["lecture"]["id"]]
    assert ids(client, topic_id=s["python"]["id"]) == [s["quiz"]["id"]]
    medicines = topics_by_name(client)["Medicines & doctors"]
    assert ids(client, topic_id=medicines["id"]) == [s["dentist"]["id"]]
    assert ids(client, topic_id=topics_by_name(client)["Trips & places"]["id"]) == []


def test_your_move_decides_the_topic(client, study_with_python):
    s = study_with_python
    trips = topics_by_name(client)["Trips & places"]
    move(client, s["lecture"], trips)
    assert ids(client, topic_id=s["study"]["id"]) == [s["quiz"]["id"]]
    assert ids(client, topic_id=trips["id"]) == [s["lecture"]["id"]]


def test_topic_filter_combines_with_kind_and_paging(client, study_with_python):
    s = study_with_python
    link = add_link(client)
    move(client, link, s["python"])
    study_id = s["study"]["id"]
    assert ids(client, topic_id=study_id, item_type="url") == [link["id"]]
    assert ids(client, topic_id=study_id, item_type="text", order="desc") == [s["quiz"]["id"], s["lecture"]["id"]]
    first = ids(client, topic_id=study_id, order="desc", limit=2, offset=0)
    rest = ids(client, topic_id=study_id, order="desc", limit=2, offset=2)
    assert first + rest == [link["id"], s["quiz"]["id"], s["lecture"]["id"]]


def test_someone_elses_topic_is_not_found(client, study_with_python):
    study_id = study_with_python["study"]["id"]
    client.post("/api/auth/logout")
    register(client, "second@example.com")
    assert client.get("/api/items", params={"topic_id": study_id}).status_code == 404
    assert client.get(f"/api/topics/{study_id}").status_code == 404
    assert client.get("/api/items", params={"topic_id": 0}).status_code == 422


# --- the topic page's detail ------------------------------------------------------------


def test_topic_detail_counts_notes_by_kind(client, study_with_python):
    s = study_with_python
    link = add_link(client)
    move(client, link, s["python"])
    detail = client.get(f"/api/topics/{s['study']['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["name"] == "Study" and body["bot_key"] == "learn" and body["is_built_in"]
    assert body["item_count"] == 1 and body["total_item_count"] == 3
    assert body["type_counts"] == {"text": 2, "url": 1}
    python = client.get(f"/api/topics/{s['python']['id']}").json()
    assert python["parent_topic_id"] == s["study"]["id"]
    assert python["type_counts"] == {"text": 1, "url": 1}
    assert client.get("/api/topics/999999").status_code == 404


# --- renaming ------------------------------------------------------------------------------


def test_rename_refuses_a_name_you_already_use(client):
    topics = topics_by_name(client)
    mine = client.post("/api/topics", json={"name": "Chess", "description": "Openings"}).json()
    clash = client.patch(f"/api/topics/{mine['id']}", json={"name": "  study "})
    assert clash.status_code == 400
    assert "Study" in clash.json()["detail"]
    assert topics_by_name(client)["Chess"]["id"] == mine["id"]  # unchanged
    # A change of case only, and keeping the same name, are fine.
    assert client.patch(f"/api/topics/{mine['id']}", json={"name": "chess"}).json()["name"] == "chess"
    same = client.patch(f"/api/topics/{topics['Study']['id']}", json={"name": "Study", "description": "Courses"})
    assert same.status_code == 200 and same.json()["description"] == "Courses"


def test_rename_keeps_filters_and_the_saved_analysis_in_step(client):
    lecture, dentist = add_and_file(client, "Read the lecture notes tomorrow", "Book a dentist appointment")
    study = topics_by_name(client)["Study"]
    before = client.get("/api/items", params={"category": "Study"}).json()
    assert [row["id"] for row in before] == [lecture["id"]]

    renamed = client.patch(f"/api/topics/{study['id']}", json={"name": "College"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "College"

    # The note's stored category follows the topic's new name...
    assert ids(client, category="College") == [lecture["id"]]
    assert ids(client, category="Study") == []
    # ...and so does the saved AI-organized view.
    latest = client.get("/api/analyze/latest")
    assert latest.status_code == 200, latest.text
    names = [bucket["name"] for bucket in latest.json()["buckets"]]
    assert "College" in names and "Study" not in names
    # Other topics are untouched.
    assert ids(client, category="Medicines & doctors") == [dentist["id"]]


def test_rename_only_touches_your_own_notes(client):
    add_and_file(client, "Read the lecture notes tomorrow")
    client.post("/api/auth/logout")
    register(client, "second@example.com")
    (theirs,) = add_and_file(client, "Read the lecture notes tomorrow")
    client.post("/api/auth/logout")
    login(client, "owner@example.com")
    mine = topics_by_name(client)["Study"]
    assert client.patch(f"/api/topics/{mine['id']}", json={"name": "College"}).status_code == 200
    client.post("/api/auth/logout")
    login(client, "second@example.com")
    assert ids(client, category="Study") == [theirs["id"]]
    latest = client.get("/api/analyze/latest").json()
    assert "Study" in [bucket["name"] for bucket in latest["buckets"]]
