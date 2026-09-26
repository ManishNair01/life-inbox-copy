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


def test_create_and_list_canonical_text_item(client):
    response = client.post(
        "/api/items",
        json={"raw_text": "Canonical text item"},
    )

    assert response.status_code == 200
    item = response.json()
    assert item == {
        "id": 1,
        "item_type": "text",
        "title": None,
        "raw_text": "Canonical text item",
        "source_url": None,
        "original_filename": None,
        "mime_type": None,
        "processing_status": "ready",
        "created_at": item["created_at"],
        "updated_at": None,
    }
    assert client.get("/api/items").json() == [item]


def test_update_canonical_text_item(client):
    created = client.post(
        "/api/items",
        json={"raw_text": "Original item"},
    ).json()

    response = client.put(
        f"/api/items/{created['id']}",
        json={"raw_text": "Updated item"},
    )

    assert response.status_code == 200
    updated = response.json()
    assert updated["id"] == created["id"]
    assert updated["raw_text"] == "Updated item"
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] is not None
    assert client.get("/api/notes").json() == [
        {
            "id": created["id"],
            "text": "Updated item",
            "created_at": created["created_at"],
        }
    ]


@pytest.mark.parametrize("raw_text", ["", "   \t\n", "x" * 2001])
def test_canonical_item_rejects_invalid_text(client, raw_text):
    response = client.post(
        "/api/items",
        json={"raw_text": raw_text},
    )

    assert response.status_code == 422
    assert client.get("/api/items").json() == []


@pytest.mark.parametrize("raw_text", ["", "   \t\n", "x" * 2001])
def test_canonical_item_update_rejects_invalid_text(client, raw_text):
    created = client.post(
        "/api/items",
        json={"raw_text": "Keep this item"},
    ).json()

    response = client.put(
        f"/api/items/{created['id']}",
        json={"raw_text": raw_text},
    )

    assert response.status_code == 422
    assert client.get("/api/items").json() == [created]


def test_canonical_item_missing_ids_return_404(client):
    update_response = client.put(
        "/api/items/999",
        json={"raw_text": "Updated item"},
    )
    delete_response = client.delete("/api/items/999")

    assert update_response.status_code == 404
    assert update_response.json() == {"detail": "Item not found."}
    assert delete_response.status_code == 404
    assert delete_response.json() == {"detail": "Item not found."}


def test_delete_canonical_item_affects_only_requested_item(client):
    first = client.post(
        "/api/items", json={"raw_text": "Delete this item"}
    ).json()
    second = client.post(
        "/api/items", json={"raw_text": "Keep this item"}
    ).json()

    response = client.delete(f"/api/items/{first['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/items").json() == [second]


def test_notes_api_uses_canonical_item_storage(client):
    note = client.post(
        "/api/notes", json={"text": "Compatibility note"}
    ).json()

    items = client.get("/api/items").json()

    assert len(items) == 1
    assert items[0]["id"] == note["id"]
    assert items[0]["item_type"] == "text"
    assert items[0]["raw_text"] == note["text"]


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


def test_update_note(client):
    created = client.post(
        "/api/notes", json={"text": "Original note"}
    ).json()

    response = client.put(
        f"/api/notes/{created['id']}",
        json={"text": "Updated note"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "id": created["id"],
        "text": "Updated note",
        "created_at": created["created_at"],
    }
    assert client.get("/api/notes").json() == [response.json()]

    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        stored_item = session.get(database.InboxItemRecord, created["id"])
        assert stored_item.updated_at is not None


@pytest.mark.parametrize("text", ["", "   \t\n", "x" * 2001])
def test_update_note_rejects_invalid_text(client, text):
    created = client.post(
        "/api/notes", json={"text": "Keep this note"}
    ).json()

    response = client.put(
        f"/api/notes/{created['id']}",
        json={"text": text},
    )

    assert response.status_code == 422
    assert client.get("/api/notes").json() == [created]


def test_update_nonexistent_note_returns_404(client):
    response = client.put(
        "/api/notes/999",
        json={"text": "Updated note"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Note not found."}


def test_delete_only_requested_note(client):
    first = client.post(
        "/api/notes", json={"text": "Delete this note"}
    ).json()
    second = client.post(
        "/api/notes", json={"text": "Keep this note"}
    ).json()

    response = client.delete(f"/api/notes/{first['id']}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/notes").json() == [second]


def test_delete_nonexistent_note_returns_404(client):
    response = client.delete("/api/notes/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Note not found."}


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


def test_update_note_returns_friendly_error(client, monkeypatch):
    main = sys.modules["app.main"]

    def fail_to_update(_note_id, _text):
        raise RuntimeError("private database location")

    monkeypatch.setattr(main, "update_note_in_db", fail_to_update)

    response = client.put(
        "/api/notes/1",
        json={"text": "Updated note"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to update note. Please try again."
    }
    assert "private database" not in response.text


def test_delete_note_returns_friendly_error(client, monkeypatch):
    main = sys.modules["app.main"]

    def fail_to_delete(_note_id):
        raise RuntimeError("private database location")

    monkeypatch.setattr(main, "delete_note_from_db", fail_to_delete)

    response = client.delete("/api/notes/1")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to delete note. Please try again."
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
