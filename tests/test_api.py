import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Create an app client backed only by a per-test SQLite database."""
    from app import database

    test_db_path = tmp_path / "life_inbox_test.db"
    monkeypatch.setattr(database, "DB_PATH", test_db_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")

    assert database.DB_PATH == test_db_path
    with TestClient(main.app) as test_client:
        yield test_client

    sys.modules.pop("app.main", None)


def test_home_page_loads(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Life Inbox</title>" in response.text
    assert "Analyze Entire Inbox with AI" in response.text


@pytest.mark.parametrize(
    ("path", "content_type", "expected_content"),
    [
        ("/static/styles.css", "text/css", ".wrap"),
        ("/static/app.js", "javascript", "async function addNote()"),
    ],
)
def test_static_assets_load(client, path, content_type, expected_content):
    response = client.get(path)

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]
    assert expected_content in response.text


def test_health_check(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_note(client):
    response = client.post("/api/notes", json={"text": "Buy milk tomorrow"})

    assert response.status_code == 200
    note = response.json()
    assert note["id"] == 1
    assert note["text"] == "Buy milk tomorrow"
    assert note["created_at"]


def test_list_saved_notes(client):
    first = client.post("/api/notes", json={"text": "First note"})
    second = client.post("/api/notes", json={"text": "Second note"})

    response = client.get("/api/notes")

    assert first.status_code == 200
    assert second.status_code == 200
    assert response.status_code == 200
    assert [note["text"] for note in response.json()] == [
        "First note",
        "Second note",
    ]


@pytest.mark.parametrize("text", ["", "   \t\n", "x" * 2001])
def test_invalid_note_text_is_rejected(client, text):
    response = client.post("/api/notes", json={"text": text})

    assert response.status_code == 422
    assert client.get("/api/notes").json() == []


def test_analyze_empty_inbox(client):
    response = client.post("/api/analyze")

    assert response.status_code == 200
    assert response.json() == {
        "buckets": [],
        "todos": [],
        "priority_view": {"High": [], "Medium": [], "Low": []},
        "mode": "empty_inbox",
    }


def test_analyze_uses_deterministic_fallback_without_openai_key(client):
    note_text = "Call the team tomorrow"
    create_response = client.post("/api/notes", json={"text": note_text})

    response = client.post("/api/analyze")

    assert create_response.status_code == 200
    assert response.status_code == 200
    assert response.json() == {
        "buckets": [
            {
                "name": "Work",
                "notes": [
                    {
                        "id": 1,
                        "title": note_text,
                        "priority": "High",
                    }
                ],
            }
        ],
        "todos": [
            {
                "task": note_text,
                "priority": "High",
                "source_note_ids": [1],
                "when": None,
            }
        ],
        "priority_view": {
            "High": [{"id": 1, "title": note_text}],
            "Medium": [],
            "Low": [],
        },
        "mode": "fallback_no_api_call",
    }
