import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Create an app client backed only by a per-test SQLite database."""
    test_db_path = tmp_path / "life_inbox_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    sys.modules.pop("app.database", None)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")

    assert database.engine.url.database == str(test_db_path)
    with TestClient(main.app) as test_client:
        yield test_client

    database.engine.dispose()
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.database", None)


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


def test_create_note_returns_friendly_error(client, monkeypatch):
    main = sys.modules["app.main"]

    def fail_to_save(_text):
        raise RuntimeError("database password should not be exposed")

    monkeypatch.setattr(main, "add_note_to_db", fail_to_save)

    response = client.post("/api/notes", json={"text": "Keep this text"})

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to save note. Please try again."
    }
    assert "password" not in response.text


def test_list_notes_returns_friendly_error(client, monkeypatch):
    main = sys.modules["app.main"]

    def fail_to_list():
        raise RuntimeError("private database location")

    monkeypatch.setattr(main, "list_notes_from_db", fail_to_list)

    response = client.get("/api/notes")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to load notes. Please try again."
    }
    assert "private database" not in response.text


def test_analyze_returns_friendly_error(client, monkeypatch):
    main = sys.modules["app.main"]

    def fail_to_analyze(_notes):
        raise RuntimeError("OPENAI_API_KEY=super-secret")

    monkeypatch.setattr(main, "analyze_inbox_with_openai", fail_to_analyze)

    response = client.post("/api/analyze")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to analyze inbox. Please try again."
    }
    assert "super-secret" not in response.text


def test_openai_failure_fallback_omits_technical_details(monkeypatch):
    import openai

    from app import organizer

    def fail_client_creation():
        raise RuntimeError("OPENAI_API_KEY=super-secret")

    monkeypatch.setenv("OPENAI_API_KEY", "configured-for-test")
    monkeypatch.setattr(openai, "OpenAI", fail_client_creation)

    result = organizer.analyze_inbox_with_openai(
        [
            {
                "id": 1,
                "text": "Call the team tomorrow",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ]
    )

    assert result["mode"] == "fallback_after_api_error"
    assert "error" not in result
    assert "super-secret" not in repr(result)
