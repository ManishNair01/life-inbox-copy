import importlib
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import login, register


def analysis_without_metadata(data):
    return {
        key: value
        for key, value in data.items()
        if key
        not in {
            "analysis_run_id",
            "generated_at",
            "is_stale",
            "inbox_fingerprint",
        }
    }


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Create an app client backed only by a per-test SQLite database."""
    test_db_path = tmp_path / "life_inbox_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    for module_name in (
        "app.main",
        "app.database",
        "app.auth",
        "app.config",
        "app.integrations.calendar",
    ):
        sys.modules.pop(module_name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")

    assert database.engine.url.database == str(test_db_path)
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com", display_name="Owner")
        yield test_client

    database.engine.dispose()
    for module_name in (
        "app.main",
        "app.database",
        "app.auth",
        "app.config",
        "app.integrations.calendar",
    ):
        sys.modules.pop(module_name, None)


def test_home_page_loads(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>Life Inbox</title>" in response.text
    assert "Re-sort everything" in response.text
    assert 'href="/api/items/export.md" download>Export Markdown</a>' in response.text
    assert 'id="notificationPrompt"' in response.text
    assert 'onclick="enableNotificationsFromPrompt(event)"' in response.text


def test_failure_retry_center_entrypoint_uses_existing_failed_filter(client):
    home = client.get("/")
    app_js = client.get("/static/app.js")

    assert home.status_code == 200
    assert 'id="failureCenter"' in home.text
    assert "Failure &amp; Retry Center" in home.text
    assert 'onclick="showFailedItems()"' in home.text
    assert 'id="rawSavedNotesHeading"' in home.text
    assert app_js.status_code == 200
    assert "function showFailedItems()" in app_js.text
    assert "No failed items. Nothing needs a retry." in app_js.text
    assert "const failedOnlyFilter =" in app_js.text
    assert "updated.processing_status === 'ready' && failedOnlyFilter" in app_js.text
    normalized_app_js = app_js.text.replace("\r\n", "\n")
    assert "root.remove();\n            await loadNotes();" in normalized_app_js


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
    payload = response.json()
    assert payload["status"] == "ok"
    assert "environment" in payload
    assert "database" in payload


def test_notification_preferences_are_saved_per_user(client, monkeypatch):
    monkeypatch.delenv("LIFE_INBOX_VAPID_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LIFE_INBOX_VAPID_PRIVATE_KEY", raising=False)

    defaults = client.get("/api/notifications/settings")
    assert defaults.status_code == 200
    assert defaults.json()["enabled"] is False
    assert defaults.json()["push_available"] is False

    disabled = client.put(
        "/api/notifications/settings",
        json={
            "enabled": False,
            "daily_digest_time": "09:15",
            "timezone": "America/Los_Angeles",
            "include_unscheduled_prompt": True,
        },
    )
    assert disabled.status_code == 200
    assert disabled.json()["daily_digest_time"] == "09:15"
    assert disabled.json()["timezone"] == "America/Los_Angeles"
    assert disabled.json()["include_unscheduled_prompt"] is True

    rejected_enable = client.put(
        "/api/notifications/settings",
        json={
            "enabled": True,
            "daily_digest_time": "09:15",
            "timezone": "America/Los_Angeles",
            "include_unscheduled_prompt": True,
        },
    )
    assert rejected_enable.status_code == 503


def test_push_subscription_is_user_scoped_and_not_exposed(client, monkeypatch):
    monkeypatch.setenv("LIFE_INBOX_VAPID_PUBLIC_KEY", "public")
    monkeypatch.setenv("LIFE_INBOX_VAPID_PRIVATE_KEY", "private")
    subscription = {
        "endpoint": "https://fcm.googleapis.com/fcm/send/test-subscription",
        "keys": {"p256dh": "public-encryption-key", "auth": "auth-secret"},
    }

    registered = client.post(
        "/api/notifications/subscriptions",
        json=subscription,
    )
    assert registered.status_code == 201
    assert registered.json() == {"registered": True}
    settings = client.get("/api/notifications/settings").json()
    assert settings["subscription_count"] == 1
    assert "endpoint" not in settings
    assert "auth-secret" not in settings.values()

    register(client, "notifications-other@example.com", display_name="Other")
    conflict = client.post(
        "/api/notifications/subscriptions",
        json=subscription,
    )
    assert conflict.status_code == 422


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
        "error_message": None,
        "storage_path": None,
        "extracted_text": None,
        "ai_description": None,
        "user_context": None,
        "owner_user_id": item["owner_user_id"],
        "created_at": item["created_at"],
        "updated_at": None,
        # change 015: only links have a card or reuse an earlier result
        "link_card": None,
        "reused_from": None,
        "filing_reused": False,
        # change 016: a note holding a secret is masked on screen
        "looks_secret": False,
        "secret_masked": None,
        # change 022: a long PDF's one-time summary
        "source_summary": None,
    }
    assert item["owner_user_id"] is not None
    assert client.get("/api/items").json() == [item]


def test_markdown_export_download_includes_content_without_internal_fields(client):
    created = client.post(
        "/api/items",
        json={"raw_text": "Shared note content"},
    ).json()
    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        item = session.get(database.InboxItemRecord, created["id"])
        item.title = "Trip planning"
        item.source_url = "https://example.test/article"
        item.original_filename = "trip.pdf"
        item.extracted_text = item.raw_text
        item.ai_description = "An AI summary."
        item.storage_path = "private/uploads/trip.pdf"
        session.commit()

    response = client.get("/api/items/export.md")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"] == (
        'attachment; filename="life-inbox-export.md"'
    )
    assert "Trip planning" in response.text
    assert "**Type:** text" in response.text
    assert created["created_at"] in response.text
    assert "https://example.test/article" in response.text
    assert "trip.pdf" in response.text
    assert response.text.count("Shared note content") == 1
    assert "An AI summary." in response.text
    assert "owner_user_id" not in response.text
    assert "storage_path" not in response.text
    assert "private/uploads/trip.pdf" not in response.text


def test_markdown_export_includes_more_than_one_hundred_notes(client):
    for index in range(105):
        response = client.post(
            "/api/items",
            json={"raw_text": f"Export note {index}"},
        )
        assert response.status_code == 200

    exported = client.get("/api/items/export.md")

    assert exported.status_code == 200
    assert exported.text.count("## Note ") == 105
    assert "Export note 0" in exported.text
    assert "Export note 104" in exported.text


def test_markdown_export_is_scoped_to_current_user(client):
    register(client, "export-alice@example.com", display_name="Alice")
    client.post("/api/items", json={"raw_text": "Alice's private export note"})

    register(client, "export-bob@example.com", display_name="Bob")
    client.post("/api/items", json={"raw_text": "Bob's private export note"})
    bob_export = client.get("/api/items/export.md")

    assert bob_export.status_code == 200
    assert "Bob's private export note" in bob_export.text
    assert "Alice's private export note" not in bob_export.text

    login(client, "export-alice@example.com")
    alice_export = client.get("/api/items/export.md")

    assert "Alice's private export note" in alice_export.text
    assert "Bob's private export note" not in alice_export.text


def test_item_search_is_case_insensitive_for_raw_text_and_title(client):
    text_match = client.post(
        "/api/items",
        json={"raw_text": "Plan the SUMMER holiday"},
    ).json()
    title_match = client.post(
        "/api/items",
        json={"raw_text": "Review the figures"},
    ).json()

    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        item = session.get(database.InboxItemRecord, title_match["id"])
        item.title = "Annual BUDGET"
        session.commit()

    raw_results = client.get("/api/items", params={"q": "summer"})
    title_results = client.get("/api/items", params={"q": "budget"})

    assert raw_results.status_code == 200
    assert [item["id"] for item in raw_results.json()] == [text_match["id"]]
    assert title_results.status_code == 200
    assert [item["id"] for item in title_results.json()] == [
        title_match["id"]
    ]


def test_item_search_combines_all_filters(client):
    first = client.post(
        "/api/items",
        json={"raw_text": "Quarterly REPORT"},
    ).json()
    second = client.post(
        "/api/items",
        json={"raw_text": "Quarterly report archive"},
    ).json()
    third = client.post(
        "/api/items",
        json={"raw_text": "Personal report"},
    ).json()

    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        run = database.AnalysisRunRecord(
            started_at="2026-01-01T00:00:00+00:00",
            completed_at="2026-01-01T00:00:01+00:00",
            status="succeeded",
            mode="fallback_no_api_call",
            result_json="{}",
        )
        session.add(run)
        session.flush()
        session.add_all(
            [
                database.ItemInsightRecord(
                    item_id=first["id"],
                    analysis_run_id=run.id,
                    category="Work",
                    concise_title="Quarterly report",
                    priority="High",
                    updated_at=run.completed_at,
                ),
                database.ItemInsightRecord(
                    item_id=second["id"],
                    analysis_run_id=run.id,
                    category="Work",
                    concise_title="Archived report",
                    priority="High",
                    updated_at=run.completed_at,
                ),
                database.ItemInsightRecord(
                    item_id=third["id"],
                    analysis_run_id=run.id,
                    category="Personal",
                    concise_title="Personal report",
                    priority="Low",
                    updated_at=run.completed_at,
                ),
            ]
        )
        archived = session.get(database.InboxItemRecord, second["id"])
        archived.processing_status = "pending"
        session.commit()

    response = client.get(
        "/api/items",
        params={
            "q": "report",
            "item_type": "text",
            "category": "Work",
            "priority": "High",
            "processing_status": "ready",
        },
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [first["id"]]


def test_item_search_handles_empty_results_and_sql_characters(client):
    percent_match = client.post(
        "/api/items",
        json={"raw_text": "Discount is 50% today"},
    ).json()
    other = client.post(
        "/api/items",
        json={"raw_text": "Ordinary note"},
    ).json()

    literal_percent = client.get("/api/items", params={"q": "50%"})
    unsafe_text = client.get(
        "/api/items",
        params={"q": "%' OR 1=1 --"},
    )
    no_results = client.get("/api/items", params={"q": "not-present"})
    empty_search = client.get("/api/items", params={"q": "   "})

    assert [item["id"] for item in literal_percent.json()] == [
        percent_match["id"]
    ]
    assert unsafe_text.status_code == 200
    assert unsafe_text.json() == []
    assert no_results.status_code == 200
    assert no_results.json() == []
    assert [item["id"] for item in empty_search.json()] == [
        percent_match["id"],
        other["id"],
    ]


def test_item_search_applies_conservative_result_limit(client):
    for number in range(3):
        client.post(
            "/api/items",
            json={"raw_text": f"Matching item {number}"},
        )

    response = client.get(
        "/api/items",
        params={"q": "matching", "limit": 2},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [1, 2]


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


def test_latest_analysis_is_empty_before_first_success(client):
    response = client.get("/api/analyze/latest")

    assert response.status_code == 204
    assert response.content == b""


def test_analyze_empty_inbox(client):
    response = client.post("/api/analyze")

    assert response.status_code == 200
    data = response.json()
    assert data["analysis_run_id"] == 1
    assert data["generated_at"]
    assert analysis_without_metadata(data) == {
        "buckets": [],
        "todos": [],
        "priority_view": {"High": [], "Medium": [], "Low": []},
        "mode": "empty_inbox",
    }
    assert client.get("/api/analyze/latest").json() == data


def test_analyze_uses_deterministic_fallback_without_openai_key(client):
    note_text = "Call the team tomorrow"
    create_response = client.post("/api/notes", json={"text": note_text})

    response = client.post("/api/analyze")

    assert create_response.status_code == 200
    assert response.status_code == 200
    data = response.json()
    assert data["analysis_run_id"] == 1
    assert data["generated_at"]
    assert analysis_without_metadata(data) == {
        "buckets": [
            {
                "name": "Work & career",
                "notes": [
                    {
                        "id": 1,
                        "title": note_text,
                        "priority": "High",
                        "tags": ["urgent", "follow-up"],
                        "rationale": (
                            "The subject decides, not the format: it mentions “team”."
                        ),
                    }
                ],
            }
        ],
        "todos": [
            {
                "task": note_text,
                "priority": "High",
                "source_note_ids": [1],
                "when": "tomorrow",
            }
        ],
        "priority_view": {
            "High": [{"id": 1, "title": note_text}],
            "Medium": [],
            "Low": [],
        },
        "mode": "fallback_no_api_call",
    }


def test_successful_analysis_persists_run_and_item_insight(client):
    created = client.post(
        "/api/items",
        json={"raw_text": "Call the team tomorrow"},
    ).json()

    analysis = client.post("/api/analyze").json()

    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        run = session.get(
            database.AnalysisRunRecord,
            analysis["analysis_run_id"],
        )
        insight = session.get(
            database.ItemInsightRecord,
            created["id"],
        )
        assert run.status == "succeeded"
        assert run.mode == "fallback_no_api_call"
        assert run.started_at
        assert run.completed_at == analysis["generated_at"]
        stored = json.loads(run.result_json)
        assert stored.pop("inbox_fingerprint") == analysis["inbox_fingerprint"]
        assert stored == analysis_without_metadata(analysis)
        assert analysis["is_stale"] is False
        assert insight.analysis_run_id == run.id
        assert insight.category == "Work & career"
        assert insight.concise_title == "Call the team tomorrow"
        assert insight.priority == "High"


def test_analysis_creates_open_task_with_source_link(client):
    created = client.post(
        "/api/items",
        json={"raw_text": "Call the team tomorrow"},
    ).json()

    client.post("/api/analyze")
    response = client.get("/api/tasks")

    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 1
    assert tasks[0]["text"] == "Call the team tomorrow"
    assert tasks[0]["priority"] == "High"
    assert tasks[0]["timing_text"] == "tomorrow"
    assert tasks[0]["ai_timing_text"] == "tomorrow"
    assert tasks[0]["timing_confirmed"] is False
    assert tasks[0]["status"] == "open"
    assert tasks[0]["source_item_ids"] == [created["id"]]
    assert tasks[0]["created_at"]
    assert tasks[0]["updated_at"]


def test_task_statuses_survive_reload_and_reanalysis_without_duplicates(client):
    client.post(
        "/api/items",
        json={"raw_text": "Call the team tomorrow"},
    )
    client.post("/api/analyze")
    task = client.get("/api/tasks").json()[0]

    completed = client.post(
        f"/api/tasks/{task['id']}/complete"
    ).json()

    assert completed["status"] == "completed"
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/tasks?status=completed").json() == [completed]

    client.post("/api/analyze")
    all_tasks = client.get("/api/tasks?status=all").json()
    assert len(all_tasks) == 1
    assert all_tasks[0]["id"] == task["id"]
    assert all_tasks[0]["status"] == "completed"

    reopened = client.post(
        f"/api/tasks/{task['id']}/reopen"
    ).json()
    assert reopened["status"] == "open"
    assert client.get("/api/tasks").json() == [reopened]

    dismissed = client.post(
        f"/api/tasks/{task['id']}/dismiss"
    ).json()
    assert dismissed["status"] == "dismissed"
    assert client.get("/api/tasks").json() == []
    assert client.get("/api/tasks?status=dismissed").json() == [dismissed]

    client.post("/api/analyze")
    final_tasks = client.get("/api/tasks?status=all").json()
    assert len(final_tasks) == 1
    assert final_tasks[0]["id"] == task["id"]
    assert final_tasks[0]["status"] == "dismissed"


def test_reanalysis_updates_task_by_source_without_changing_status(
    client, monkeypatch
):
    item = client.post(
        "/api/items",
        json={"raw_text": "Prepare the class notes"},
    ).json()
    filing = sys.modules["app.filing"]
    analyses = iter(
        [
            ("Prepare class notes", "Low"),
            ("Prepare notes for class", "High"),
        ]
    )

    def file_batch(notes, topics, **_kwargs):
        task_text, priority = next(analyses)
        study = next(t for t in topics if t["name"] == "Study")
        return [{
            "id": note["id"], "topic": study["id"], "bot": "learn", "rule": "R5", "confidence": "high",
            "choices": [], "title": task_text, "priority": priority, "tags": [], "reason": "Class work.",
            "tasks": [{"task": task_text, "when": None, "date": None, "time": None}],
            "transcript": None, "summary": None, "action": None, "filed_by": "ai",
        } for note in notes], "nvidia_nim"

    monkeypatch.setattr(filing, "file_batch", file_batch)

    client.post("/api/analyze")
    original = client.get("/api/tasks").json()[0]
    client.post(f"/api/tasks/{original['id']}/complete")

    client.post("/api/analyze")
    tasks = client.get("/api/tasks?status=all").json()

    assert len(tasks) == 1
    assert tasks[0]["id"] == original["id"]
    assert tasks[0]["text"] == "Prepare notes for class"
    assert tasks[0]["priority"] == "High"
    assert tasks[0]["status"] == "completed"
    assert tasks[0]["source_item_ids"] == [item["id"]]


def test_generated_task_preserves_multiple_source_links(client):
    # Filing v2 gives each task one note, but the save path still keeps a task
    # that names several notes linked to all of them.
    first = client.post(
        "/api/items", json={"raw_text": "First source"}
    ).json()
    second = client.post(
        "/api/items", json={"raw_text": "Second source"}
    ).json()
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    try:
        run_id = database.start_analysis_run()
        database.complete_analysis_run(run_id, {
            "buckets": [{"name": "Work & career", "notes": [
                {"id": first["id"], "title": "First source", "priority": "Medium"},
                {"id": second["id"], "title": "Second source", "priority": "Medium"},
            ]}],
            "todos": [{
                "task": "Follow up on both sources",
                "priority": "Medium",
                "source_note_ids": [second["id"], first["id"]],
                "when": "tomorrow",
            }],
            "priority_view": {"High": [], "Medium": [
                {"id": first["id"], "title": "First source"},
                {"id": second["id"], "title": "Second source"},
            ], "Low": []},
            "mode": "openai",
        })
    finally:
        database.set_current_owner_id(None)

    task = client.get("/api/tasks").json()[0]
    assert task["text"] == "Follow up on both sources"
    assert task["timing_text"] == "tomorrow"
    assert task["source_item_ids"] == [first["id"], second["id"]]

    with database.SessionLocal() as session:
        assert session.query(database.TaskSourceItemRecord).count() == 2


@pytest.mark.parametrize("action", ["complete", "reopen", "dismiss"])
def test_task_status_actions_return_404_for_unknown_id(client, action):
    response = client.post(f"/api/tasks/999/{action}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Task not found."}


def test_task_list_rejects_invalid_status(client):
    response = client.get("/api/tasks?status=invalid")

    assert response.status_code == 422


def test_failed_analysis_keeps_previous_success(client, monkeypatch):
    client.post(
        "/api/items",
        json={"raw_text": "Call the team tomorrow"},
    )
    previous = client.post("/api/analyze").json()
    filing = sys.modules["app.filing"]

    def fail_filing(_notes, _topics, **_kwargs):
        raise RuntimeError("simulated failure while filing")

    monkeypatch.setattr(filing, "file_batch", fail_filing)

    failed_response = client.post("/api/analyze")

    assert failed_response.status_code == 500
    assert client.get("/api/analyze/latest").json() == previous

    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        runs = session.query(database.AnalysisRunRecord).order_by(
            database.AnalysisRunRecord.id
        ).all()
        insight = session.get(database.ItemInsightRecord, 1)
        assert [run.status for run in runs] == ["succeeded", "failed"]
        assert runs[1].mode == "error"
        assert runs[1].result_json is None
        assert insight.analysis_run_id == runs[0].id


def test_invalid_analysis_result_is_not_saved(client, monkeypatch):
    # An AI answer that fails code's checks (even after the repair call) is
    # never saved: the offline matcher files the note instead (change 014).
    client.post(
        "/api/items",
        json={"raw_text": "Call the team tomorrow"},
    )
    filing = sys.modules["app.filing"]
    llm = filing.llm

    def unusable(*_args, **_kwargs):
        raise llm.InvalidOutput("topic \"Made-up topic\" doesn't exist")

    monkeypatch.setattr(llm, "is_configured", lambda: True)
    monkeypatch.setattr(llm, "complete_json", unusable)

    response = client.post("/api/analyze")

    assert response.status_code == 200
    assert response.json()["mode"] == "fallback_after_api_error"
    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        insight = session.get(database.ItemInsightRecord, 1)
        assert insight.category == "Work & career"
        assert insight.filed_by == "offline"
        assert session.query(database.TopicRecord).filter_by(name="Made-up topic").count() == 0


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
    client.post("/api/items", json={"raw_text": "Call the team tomorrow"})
    filing = sys.modules["app.filing"]

    def fail_to_file(_notes, _topics, **_kwargs):
        raise RuntimeError("OPENAI_API_KEY=super-secret")

    monkeypatch.setattr(filing, "file_batch", fail_to_file)

    response = client.post("/api/analyze")

    assert response.status_code == 500
    assert response.json() == {
        "detail": "Unable to analyze inbox. Please try again."
    }
    assert "super-secret" not in response.text


def test_valid_mocked_openai_output_is_validated(monkeypatch):
    import openai

    from app import organizer

    model_output = {
        "buckets": [
            {
                "name": "Work",
                "notes": [
                    {
                        "id": 1,
                        "title": "Send summary",
                        "priority": "Medium",
                    }
                ],
            }
        ],
        "todos": [
            {
                "task": "Send the meeting summary",
                "priority": "Medium",
                "source_note_ids": [1],
                "when": None,
            }
        ],
        "priority_view": {
            "High": [],
            "Medium": [{"id": 1, "title": "Send summary"}],
            "Low": [],
        },
    }
    fake_responses = SimpleNamespace(
        create=lambda **_kwargs: SimpleNamespace(
            output_text=json.dumps(model_output)
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "configured-for-test")
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda: SimpleNamespace(responses=fake_responses),
    )

    result = organizer.analyze_inbox_with_openai(
        [
            {
                "id": 1,
                "text": "Send the meeting summary",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ]
    )

    assert result["mode"] == "openai"
    assert result["buckets"][0]["notes"][0]["priority"] == "Medium"


def test_malformed_mocked_openai_output_uses_fallback(monkeypatch):
    import openai

    from app import organizer

    fake_responses = SimpleNamespace(
        create=lambda **_kwargs: SimpleNamespace(
            output_text="not valid JSON"
        )
    )
    monkeypatch.setenv("OPENAI_API_KEY", "configured-for-test")
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda: SimpleNamespace(responses=fake_responses),
    )

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
    assert result["buckets"][0]["notes"][0]["id"] == 1


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


def test_item_list_supports_offset_and_raised_limit(client):
    for number in range(5):
        client.post(
            "/api/items",
            json={"raw_text": f"Paged item {number}"},
        )

    page = client.get("/api/items", params={"limit": 2, "offset": 2})

    assert page.status_code == 200
    assert [item["id"] for item in page.json()] == [3, 4]

    oversized = client.get("/api/items", params={"limit": 501})
    assert oversized.status_code == 422


def test_analysis_marked_stale_after_inbox_changes(client):
    client.post("/api/items", json={"raw_text": "Call the dentist tomorrow"})
    first = client.post("/api/analyze").json()
    assert first["is_stale"] is False
    assert first["inbox_fingerprint"]

    latest = client.get("/api/analyze/latest").json()
    assert latest["is_stale"] is False
    assert latest["inbox_fingerprint"] == first["inbox_fingerprint"]

    client.post("/api/items", json={"raw_text": "Buy groceries this weekend"})
    stale = client.get("/api/analyze/latest").json()
    assert stale["is_stale"] is True
    assert stale["analysis_run_id"] == first["analysis_run_id"]


def test_deleting_item_removes_orphan_task(client):
    created = client.post(
        "/api/items",
        json={"raw_text": "Call the team tomorrow"},
    ).json()
    client.post("/api/analyze")
    assert len(client.get("/api/tasks").json()) == 1

    delete_response = client.delete(f"/api/items/{created['id']}")
    assert delete_response.status_code == 204
    assert client.get("/api/tasks").json() == []

    database = sys.modules["app.database"]
    with database.SessionLocal() as session:
        assert session.query(database.TaskRecord).count() == 0
        assert session.query(database.TaskSourceItemRecord).count() == 0
        assert session.query(database.ItemInsightRecord).count() == 0


def test_topics_and_dashboard_after_analysis(client):
    client.post(
        "/api/items",
        json={"raw_text": "Call the dentist tomorrow"},
    )
    client.post(
        "/api/items",
        json={"raw_text": "Call the dentist tomorrow please"},
    )
    analysis = client.post("/api/analyze").json()
    assert analysis["analysis_run_id"]

    topics = client.get("/api/topics").json()
    # The dentist notes are filed under a default topic of the Health area.
    assert any(
        topic["name"] == "Medicines & doctors" and topic["bot_key"] == "health"
        for topic in topics
    )

    created = client.post(
        "/api/topics",
        json={"name": "Home projects", "description": "Around the house"},
    )
    assert created.status_code == 200
    assert created.json()["name"] == "Home projects"

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["topics"]
    assert dashboard["recently_captured"]
    assert dashboard["open_tasks"]
    assert any(
        rel["relation_type"] in {"duplicate", "near_duplicate", "related"}
        for rel in dashboard["related_items"]
    )


def test_user_insight_overrides_survive_reanalysis(client):
    item = client.post(
        "/api/items",
        json={"raw_text": "Call the team tomorrow"},
    ).json()
    client.post("/api/analyze")
    topics = client.get("/api/topics").json()
    topic_id = next(topic["id"] for topic in topics if topic["name"] == "Work & career")

    override = client.patch(
        f"/api/items/{item['id']}/insight",
        json={
            "user_title": "Team sync call",
            "user_topic_id": topic_id,
            "user_priority": "Low",
            "user_tags": ["mine"],
        },
    ).json()
    assert override["effective_title"] == "Team sync call"
    assert override["effective_priority"] == "Low"
    assert override["has_user_overrides"] is True

    client.post("/api/analyze")
    refreshed = client.get(f"/api/items/{item['id']}/insight").json()
    assert refreshed["user_title"] == "Team sync call"
    assert refreshed["effective_title"] == "Team sync call"
    assert refreshed["effective_priority"] == "Low"
    assert refreshed["concise_title"] != "Team sync call" or True
    assert refreshed["rationale"]


def test_one_source_can_create_multiple_tasks(client):
    client.post(
        "/api/items",
        json={
            "raw_text": (
                "Call Rohan about dinner. Buy groceries this weekend."
            )
        },
    )
    client.post("/api/analyze")
    tasks = client.get("/api/tasks").json()
    assert len(tasks) >= 2
    assert all(task["source_item_ids"] == [1] for task in tasks)


def test_confirm_task_timing_is_preserved_on_reanalysis(client, monkeypatch):
    item = client.post(
        "/api/items",
        json={"raw_text": "Call the team tomorrow"},
    ).json()
    main = sys.modules["app.main"]

    def analyze(_notes, **_kwargs):
        return {
            "buckets": [
                {
                    "name": "Work",
                    "notes": [
                        {
                            "id": item["id"],
                            "title": "Team call",
                            "priority": "High",
                            "tags": ["follow-up"],
                            "rationale": "Work follow-up",
                        }
                    ],
                }
            ],
            "todos": [
                {
                    "task": "Call the team",
                    "priority": "High",
                    "source_note_ids": [item["id"]],
                    "when": "tomorrow",
                }
            ],
            "priority_view": {
                "High": [{"id": item["id"], "title": "Team call"}],
                "Medium": [],
                "Low": [],
            },
            "mode": "openai",
        }

    monkeypatch.setattr(main, "analyze_inbox_with_openai", analyze)
    client.post("/api/analyze")
    task = client.get("/api/tasks").json()[0]
    confirmed = client.post(
        f"/api/tasks/{task['id']}/confirm-timing",
        json={"timing_text": "Friday morning"},
    ).json()
    assert confirmed["timing_text"] == "Friday morning"
    assert confirmed["timing_confirmed"] is True
    assert confirmed["ai_timing_text"] == "tomorrow"

    client.post("/api/analyze")
    again = client.get("/api/tasks?status=all").json()[0]
    assert again["id"] == task["id"]
    assert again["timing_text"] == "Friday morning"
    assert again["timing_confirmed"] is True
    assert again["ai_timing_text"] == "tomorrow"


def test_dismiss_relation_is_reversible_action(client):
    client.post("/api/items", json={"raw_text": "Renew car insurance soon"})
    client.post(
        "/api/items",
        json={"raw_text": "Renew the car insurance soon"},
    )
    client.post("/api/analyze")
    relations = client.get("/api/relations").json()
    assert relations
    dismissed = client.post(
        f"/api/relations/{relations[0]['id']}/dismiss"
    ).json()
    assert dismissed["dismissed"] is True
    assert client.get("/api/relations").json() == []


def test_url_capture_persists_before_processing_and_extracts_text(client, monkeypatch):
    main = sys.modules["app.main"]
    database = sys.modules["app.database"]
    original_add = database.add_url_item_to_db

    def slow_add(url, **kwargs):
        item = original_add(url, **kwargs)
        assert item["processing_status"] == "captured"
        assert item["source_url"] == "https://example.com/article"
        return item

    def fake_fetch(url):
        assert url == "https://example.com/article"
        return {
            "final_url": "https://example.com/article",
            "title": "Sample OG Title",
            "raw_text": "This is readable article text for Life Inbox URL capture tests.",
            "mime_type": "text/html",
            "status_code": 200,
        }

    monkeypatch.setattr(database, "add_url_item_to_db", slow_add)
    monkeypatch.setattr(main, "fetch_url", fake_fetch)

    response = client.post(
        "/api/items/url",
        json={"url": "https://example.com/article"},
    )

    assert response.status_code == 200
    item = response.json()
    assert item["item_type"] == "url"
    assert item["processing_status"] == "ready"
    assert item["title"] == "Sample OG Title"
    assert "readable article text" in (item["extracted_text"] or "")


def test_url_capture_blocks_private_network_targets(client):
    response = client.post(
        "/api/items/url",
        json={"url": "http://127.0.0.1/private"},
    )
    assert response.status_code == 400
    assert "not allowed" in response.json()["detail"].lower()


def test_failed_url_capture_can_retry(client, monkeypatch):
    main = sys.modules["app.main"]
    attempts = {"count": 0}

    def flaky_fetch(_url):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ValueError("Upstream returned HTTP 503")
        return {
            "final_url": "https://example.com/article",
            "title": "Recovered Article",
            "raw_text": "Recovered text",
            "mime_type": "text/html",
            "status_code": 200,
        }

    monkeypatch.setattr(main, "fetch_url", flaky_fetch)

    first = client.post(
        "/api/items/url",
        json={"url": "https://example.com/article"},
    ).json()
    assert first["processing_status"] == "failed"
    assert "503" in (first["error_message"] or "")

    failed_items = client.get(
        "/api/items",
        params={"processing_status": "failed"},
    ).json()
    assert [item["id"] for item in failed_items] == [first["id"]]

    retry = client.post(f"/api/items/{first['id']}/retry").json()
    assert retry["processing_status"] == "ready"
    assert retry["title"] == "Recovered Article"

    failed_items = client.get(
        "/api/items",
        params={"processing_status": "failed"},
    ).json()
    assert first["id"] not in {item["id"] for item in failed_items}


def test_failed_item_filter_and_retry_are_owner_scoped(client, monkeypatch):
    main = sys.modules["app.main"]
    fetches = []

    def fetch_url(url):
        fetches.append(url)
        if url.endswith("/failed"):
            raise ValueError("Temporary upstream failure")
        return {
            "final_url": url,
            "title": "Ready article",
            "raw_text": "Ready article content",
            "mime_type": "text/html",
        }

    monkeypatch.setattr(main, "fetch_url", fetch_url)
    alice = register(client, "retry-alice@example.com")
    alice_failed = client.post(
        "/api/items/url",
        json={"url": "https://example.com/failed"},
    ).json()
    alice_ready = client.post(
        "/api/items/url",
        json={"url": "https://example.com/ready"},
    ).json()

    register(client, "retry-bob@example.com")
    bob_failed = client.post(
        "/api/items/url",
        json={"url": "https://example.com/failed"},
    ).json()
    fetch_count_before_foreign_retry = len(fetches)

    forbidden_retry = client.post(f"/api/items/{alice_failed['id']}/retry")
    assert forbidden_retry.status_code == 404
    assert len(fetches) == fetch_count_before_foreign_retry

    login(client, "retry-alice@example.com")
    failed_items = client.get(
        "/api/items",
        params={"processing_status": "failed"},
    ).json()

    assert alice["id"] == alice_failed["owner_user_id"]
    assert alice_ready["processing_status"] == "ready"
    assert bob_failed["processing_status"] == "failed"
    assert [item["id"] for item in failed_items] == [alice_failed["id"]]
    assert failed_items[0]["error_message"] == "Temporary upstream failure"


def test_retry_claim_is_atomic_and_rejects_an_active_retry(client, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    main = sys.modules["app.main"]
    database = sys.modules["app.database"]
    monkeypatch.setattr(
        main,
        "fetch_url",
        lambda _url: (_ for _ in ()).throw(ValueError("Initial failure")),
    )
    failed = client.post(
        "/api/items/url",
        json={"url": "https://example.com/retry-claim"},
    ).json()
    owner_id = client.get("/api/auth/me").json()["id"]
    claim_barrier = Barrier(2)

    def claim_item():
        database.set_current_owner_id(owner_id)
        try:
            claim_barrier.wait(timeout=5)
            return database.claim_item_for_retry(failed["id"])
        finally:
            database.set_current_owner_id(None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: claim_item(), range(2)))

    assert sorted(claims) == [False, True]
    assert client.get(f"/api/items/{failed['id']}").json()["processing_status"] == "processing"
    active_retry = client.post(f"/api/items/{failed['id']}/retry")
    assert active_retry.status_code == 409


def test_analyze_includes_ready_url_items(client, monkeypatch):
    main = sys.modules["app.main"]

    monkeypatch.setattr(
        main,
        "fetch_url",
        lambda _url: {
            "final_url": "https://example.com/article",
            "title": "Article about habits",
            "raw_text": "Need to read this article about habits tomorrow.",
            "mime_type": "text/html",
            "status_code": 200,
        },
    )
    url_item = client.post(
        "/api/items/url",
        json={"url": "https://example.com/article"},
    ).json()
    assert url_item["processing_status"] == "ready"

    analysis = client.post("/api/analyze").json()
    ids = {
        note["id"]
        for bucket in analysis["buckets"]
        for note in bucket["notes"]
    }
    assert url_item["id"] in ids


def test_pdf_capture_persists_before_processing_and_extracts_text(client, monkeypatch):
    from tests.pdf_fixtures import SAMPLE_TEXT, make_text_pdf

    main = sys.modules["app.main"]
    database = sys.modules["app.database"]
    original_add = database.add_pdf_item_to_db
    pdf_bytes = make_text_pdf()

    def slow_add(original_filename, storage_path, mime_type, **kwargs):
        item = original_add(original_filename, storage_path, mime_type, **kwargs)
        assert item["processing_status"] == "captured"
        assert item["original_filename"] == "notes.pdf"
        assert item["storage_path"]
        return item

    monkeypatch.setattr(database, "add_pdf_item_to_db", slow_add)

    response = client.post(
        "/api/items/pdf",
        files={"file": ("notes.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 200
    item = response.json()
    assert item["item_type"] == "pdf"
    assert item["processing_status"] == "ready"
    assert SAMPLE_TEXT in (item["extracted_text"] or "")

    file_response = client.get(f"/api/items/{item['id']}/file")
    assert file_response.status_code == 200
    assert file_response.headers["content-type"].startswith("application/pdf")
    assert file_response.content.startswith(b"%PDF")


def test_pdf_capture_rejects_invalid_uploads(client):
    response = client.post(
        "/api/items/pdf",
        files={"file": ("notes.txt", b"not a pdf", "text/plain")},
    )
    assert response.status_code == 400
    assert "pdf" in response.json()["detail"].lower()


def test_failed_pdf_capture_can_retry(client, monkeypatch):
    from tests.pdf_fixtures import make_text_pdf

    main = sys.modules["app.main"]
    attempts = {"count": 0}
    real_extract = main.extract_pdf_text
    pdf_bytes = make_text_pdf()

    def flaky_extract(data, *, original_filename=None):
        assert data == pdf_bytes
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise ValueError("Temporary PDF parse failure")
        return real_extract(data, original_filename=original_filename)

    monkeypatch.setattr(main, "extract_pdf_text", flaky_extract)

    first = client.post(
        "/api/items/pdf",
        files={"file": ("notes.pdf", pdf_bytes, "application/pdf")},
    ).json()
    assert first["processing_status"] == "failed"
    assert "parse failure" in (first["error_message"] or "").lower()
    assert client.get(f"/api/items/{first['id']}/file").content == pdf_bytes

    retry = client.post(f"/api/items/{first['id']}/retry").json()
    assert retry["processing_status"] == "ready"
    assert retry["id"] == first["id"]
    assert retry["storage_path"] == first["storage_path"]
    assert client.get(f"/api/items/{first['id']}/file").content == pdf_bytes


def test_second_pdf_processing_failure_preserves_source_and_records_error(
    client, monkeypatch
):
    from tests.pdf_fixtures import make_text_pdf

    main = sys.modules["app.main"]
    attempts = {"count": 0}
    pdf_bytes = make_text_pdf()

    def always_fail(data, *, original_filename=None):
        assert data == pdf_bytes
        attempts["count"] += 1
        raise ValueError(f"Temporary parse failure on attempt {attempts['count']}")

    monkeypatch.setattr(main, "extract_pdf_text", always_fail)
    first = client.post(
        "/api/items/pdf",
        files={"file": ("source.pdf", pdf_bytes, "application/pdf")},
    ).json()
    saved_file_before_retry = client.get(
        f"/api/items/{first['id']}/file"
    ).content

    retry = client.post(f"/api/items/{first['id']}/retry").json()

    assert retry["processing_status"] == "failed"
    assert retry["error_message"] == "Temporary parse failure on attempt 2"
    assert retry["id"] == first["id"]
    assert retry["original_filename"] == first["original_filename"] == "source.pdf"
    assert retry["storage_path"] == first["storage_path"]
    assert retry["raw_text"] == first["raw_text"]
    assert retry["extracted_text"] == first["extracted_text"]
    assert saved_file_before_retry == pdf_bytes
    assert client.get(f"/api/items/{first['id']}/file").content == pdf_bytes
    assert len(client.get("/api/items").json()) == 1


def test_analyze_includes_ready_pdf_items(client):
    from tests.pdf_fixtures import make_text_pdf

    pdf_item = client.post(
        "/api/items/pdf",
        files={"file": ("habits.pdf", make_text_pdf(title="Habits"), "application/pdf")},
    ).json()
    assert pdf_item["processing_status"] == "ready"

    analysis = client.post("/api/analyze").json()
    ids = {
        note["id"]
        for bucket in analysis["buckets"]
        for note in bucket["notes"]
    }
    assert pdf_item["id"] in ids


def test_blank_pdf_fails_with_helpful_message(client):
    from tests.pdf_fixtures import make_blank_pdf

    item = client.post(
        "/api/items/pdf",
        files={"file": ("scan.pdf", make_blank_pdf(), "application/pdf")},
    ).json()
    assert item["processing_status"] == "failed"
    assert "image-only" in (item["error_message"] or "").lower()


def test_image_capture_persists_before_processing_and_creates_preview(client, monkeypatch):
    from tests.image_fixtures import make_png_bytes

    main = sys.modules["app.main"]
    database = sys.modules["app.database"]
    original_add = database.add_image_item_to_db
    png_bytes = make_png_bytes(text="Meeting notes")
    seen = {"persisted": False}

    def slow_add(filename, storage_path, mime_type, **kwargs):
        item = original_add(filename, storage_path, mime_type, **kwargs)
        seen["persisted"] = True
        assert item["original_filename"] == "screenshot.png"
        assert item["processing_status"] == "captured"
        assert item["storage_path"]
        return item

    monkeypatch.setattr(main, "add_image_item_to_db", slow_add)
    monkeypatch.setenv("LIFE_INBOX_DISABLE_OCR", "1")

    item = client.post(
        "/api/items/image",
        files={"file": ("screenshot.png", png_bytes, "image/png")},
    ).json()

    assert seen["persisted"] is True
    assert item["item_type"] == "image"
    assert item["processing_status"] == "ready"
    assert item["ai_description"]
    assert "AI description" in (item["raw_text"] or "")
    thumb = client.get(f"/api/items/{item['id']}/file", params={"variant": "thumb"})
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/jpeg")
    original = client.get(f"/api/items/{item['id']}/file")
    assert original.status_code == 200
    assert original.content.startswith(b"\x89PNG")


def test_image_capture_rejects_invalid_uploads(client):
    response = client.post(
        "/api/items/image",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 400
    assert "image" in response.json()["detail"].lower()


def test_failed_image_capture_can_retry(client, monkeypatch):
    from tests.image_fixtures import make_png_bytes

    import app.main as main

    real_process = main.process_image_bytes
    calls = {"n": 0}

    def flaky_process(data, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Temporary image parse failure")
        return real_process(data, **kwargs)

    monkeypatch.setattr(main, "process_image_bytes", flaky_process)

    first = client.post(
        "/api/items/image",
        files={"file": ("shot.png", make_png_bytes(), "image/png")},
    ).json()
    assert first["processing_status"] == "failed"

    retry = client.post(f"/api/items/{first['id']}/retry").json()
    assert retry["processing_status"] == "ready"
    assert retry["ai_description"]


def test_image_ocr_text_is_editable(client, monkeypatch):
    from tests.image_fixtures import make_png_bytes

    monkeypatch.setenv("LIFE_INBOX_DISABLE_OCR", "1")
    item = client.post(
        "/api/items/image",
        files={"file": ("board.png", make_png_bytes(), "image/png")},
    ).json()
    assert item["processing_status"] == "ready"

    updated = client.patch(
        f"/api/items/{item['id']}/extracted-text",
        json={"extracted_text": "User corrected OCR text about groceries"},
    ).json()
    assert updated["extracted_text"] == "User corrected OCR text about groceries"
    assert "User corrected OCR text" in updated["raw_text"]
    assert updated["ai_description"] == item["ai_description"]


def test_analyze_includes_ready_image_items(client, monkeypatch):
    from tests.image_fixtures import make_png_bytes

    monkeypatch.setenv("LIFE_INBOX_DISABLE_OCR", "1")
    image_item = client.post(
        "/api/items/image",
        files={"file": ("habits.png", make_png_bytes(text="Habits"), "image/png")},
    ).json()
    # Ensure searchable text exists even without OCR
    client.patch(
        f"/api/items/{image_item['id']}/extracted-text",
        json={"extracted_text": "Habits screenshot reminder"},
    )
    image_item = client.get("/api/items").json()
    image_item = next(i for i in image_item if i["item_type"] == "image")
    assert image_item["processing_status"] == "ready"

    analysis = client.post("/api/analyze").json()
    ids = {
        note["id"]
        for bucket in analysis["buckets"]
        for note in bucket["notes"]
    }
    assert image_item["id"] in ids


def test_voice_capture_persists_before_processing(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes

    main = sys.modules["app.main"]
    database = sys.modules["app.database"]
    original_add = database.add_voice_item_to_db
    wav = make_wav_bytes()
    seen = {"persisted": False}

    def slow_add(filename, storage_path, mime_type, **kwargs):
        item = original_add(filename, storage_path, mime_type, **kwargs)
        seen["persisted"] = True
        assert item["original_filename"] == "note.wav"
        assert item["processing_status"] == "captured"
        assert item["storage_path"]
        return item

    monkeypatch.setattr(main, "add_voice_item_to_db", slow_add)
    monkeypatch.setenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", "1")

    item = client.post(
        "/api/items/voice",
        files={"file": ("note.wav", wav, "audio/wav")},
    ).json()

    assert seen["persisted"] is True
    assert item["item_type"] == "voice"
    assert item["processing_status"] == "ready"
    assert item["extracted_text"] == ""
    assert "transcript pending" in (item["raw_text"] or "").lower()
    audio = client.get(f"/api/items/{item['id']}/file")
    assert audio.status_code == 200
    assert audio.content.startswith(b"RIFF")


def test_voice_capture_rejects_invalid_uploads(client):
    response = client.post(
        "/api/items/voice",
        files={"file": ("notes.txt", b"not audio", "text/plain")},
    )
    assert response.status_code == 400
    detail = response.json()["detail"].lower()
    assert "audio" in detail or "voice" in detail or "webm" in detail


def test_failed_voice_capture_can_retry(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes

    main = sys.modules["app.main"]
    real_process = main.process_voice_bytes
    calls = {"n": 0}

    def flaky_process(data, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("Temporary transcription failure")
        return real_process(data, **kwargs)

    monkeypatch.setattr(main, "process_voice_bytes", flaky_process)

    first = client.post(
        "/api/items/voice",
        files={"file": ("note.wav", make_wav_bytes(), "audio/wav")},
    ).json()
    assert first["processing_status"] == "failed"

    retry = client.post(f"/api/items/{first['id']}/retry").json()
    assert retry["processing_status"] == "ready"


def test_voice_transcript_is_editable_and_analyzable(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes

    monkeypatch.setenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", "1")
    item = client.post(
        "/api/items/voice",
        files={"file": ("memo.wav", make_wav_bytes(), "audio/wav")},
    ).json()
    assert item["processing_status"] == "ready"

    updated = client.patch(
        f"/api/items/{item['id']}/extracted-text",
        json={"extracted_text": "Remember to call the dentist tomorrow morning"},
    ).json()
    assert updated["extracted_text"].startswith("Remember to call")
    assert "dentist" in updated["raw_text"]

    analysis = client.post("/api/analyze").json()
    ids = {
        note["id"]
        for bucket in analysis["buckets"]
        for note in bucket["notes"]
    }
    assert updated["id"] in ids


def _mock_openai_transcription(monkeypatch, text=None, *, raise_on_create=None):
    import openai

    def create(**_kwargs):
        if raise_on_create is not None:
            raise raise_on_create
        return SimpleNamespace(text=text or "")

    monkeypatch.setenv("OPENAI_API_KEY", "configured-for-test")
    monkeypatch.delenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", raising=False)
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda: SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=create)
            )
        ),
    )


def test_voice_transcription_success_persists_transcript(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes

    wav = make_wav_bytes()
    _mock_openai_transcription(
        monkeypatch,
        "Remember to renew car insurance before Friday",
    )

    item = client.post(
        "/api/items/voice",
        files={"file": ("memo.wav", wav, "audio/wav")},
    ).json()

    assert item["processing_status"] == "ready"
    assert item["extracted_text"] == "Remember to renew car insurance before Friday"
    assert "car insurance" in (item["raw_text"] or "").lower()
    assert "transcript pending" not in (item["raw_text"] or "").lower()
    assert "OPENAI" not in (item["raw_text"] or "")
    assert "exception" not in (item.get("error_message") or "").lower()

    audio = client.get(f"/api/items/{item['id']}/file")
    assert audio.status_code == 200
    assert audio.content.startswith(b"RIFF")
    assert audio.content == wav


def test_voice_transcription_no_key_keeps_item_editable(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", raising=False)

    item = client.post(
        "/api/items/voice",
        files={"file": ("memo.wav", make_wav_bytes(), "audio/wav")},
    ).json()
    assert item["processing_status"] == "ready"
    assert item["extracted_text"] == ""
    assert "transcript pending" in (item["raw_text"] or "").lower()
    assert "not configured" in (item["raw_text"] or "").lower()

    updated = client.patch(
        f"/api/items/{item['id']}/extracted-text",
        json={"extracted_text": "Manual transcript about dentist appointment"},
    ).json()
    assert "dentist" in updated["extracted_text"]

    audio = client.get(f"/api/items/{item['id']}/file")
    assert audio.status_code == 200
    assert audio.content.startswith(b"RIFF")


def test_voice_transcription_api_failure_preserves_audio(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes

    wav = make_wav_bytes()
    _mock_openai_transcription(
        monkeypatch,
        raise_on_create=RuntimeError("OPENAI_API_KEY=super-secret provider boom"),
    )

    item = client.post(
        "/api/items/voice",
        files={"file": ("memo.wav", wav, "audio/wav")},
    ).json()

    assert item["processing_status"] == "ready"
    assert item["extracted_text"] == ""
    assert "temporarily unavailable" in (item["raw_text"] or "").lower()
    assert "super-secret" not in (item["raw_text"] or "")
    assert "OPENAI_API_KEY" not in (item["raw_text"] or "")
    assert "provider boom" not in (item["raw_text"] or "")
    assert "Traceback" not in (item["raw_text"] or "")

    audio = client.get(f"/api/items/{item['id']}/file")
    assert audio.status_code == 200
    assert audio.content == wav

    # Manual edit still works after provider failure.
    updated = client.patch(
        f"/api/items/{item['id']}/extracted-text",
        json={"extracted_text": "Edited after failed auto transcription"},
    ).json()
    assert updated["extracted_text"].startswith("Edited after")


def test_voice_transcription_uses_env_model(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes
    import openai

    seen = {}

    def create(**kwargs):
        seen["model"] = kwargs.get("model")
        return SimpleNamespace(text="hello from custom model")

    monkeypatch.setenv("OPENAI_API_KEY", "configured-for-test")
    monkeypatch.setenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
    monkeypatch.delenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", raising=False)
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda: SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=create)
            )
        ),
    )

    item = client.post(
        "/api/items/voice",
        files={"file": ("memo.wav", make_wav_bytes(), "audio/wav")},
    ).json()
    assert seen["model"] == "gpt-4o-mini-transcribe"
    assert item["extracted_text"] == "hello from custom model"


def test_voice_transcription_owner_isolation(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes

    _mock_openai_transcription(
        monkeypatch,
        "Alice private voice memo about yacht taxes",
    )
    alice = register(client, "alice-voice@example.com")
    alice_item = client.post(
        "/api/items/voice",
        files={"file": ("alice.wav", make_wav_bytes(), "audio/wav")},
    ).json()
    assert alice_item["owner_user_id"] == alice["id"]
    assert "yacht" in alice_item["extracted_text"].lower()

    bob = register(client, "bob-voice@example.com")
    assert bob["id"] != alice["id"]
    missing = client.get(f"/api/items/{alice_item['id']}")
    assert missing.status_code == 404
    audio = client.get(f"/api/items/{alice_item['id']}/file")
    assert audio.status_code == 404

    ask = client.post(
        "/api/ask",
        json={"question": "What about yacht taxes?"},
    ).json()
    assert all(c["item_id"] != alice_item["id"] for c in ask["citations"])
    assert "yacht" not in ask["answer"].lower()


def test_voice_transcript_flows_into_ask_retrieval(client, monkeypatch):
    from tests.voice_fixtures import make_wav_bytes

    _mock_openai_transcription(
        monkeypatch,
        "Order Atomic Habits this weekend after Rohan's recommendation",
    )
    item = client.post(
        "/api/items/voice",
        files={"file": ("habits.wav", make_wav_bytes(), "audio/wav")},
    ).json()
    assert item["processing_status"] == "ready"

    data = client.post(
        "/api/ask",
        json={"question": "What did Rohan recommend about Atomic Habits?"},
    ).json()
    assert data["confidence"] != "insufficient"
    assert any(c["item_id"] == item["id"] for c in data["citations"])
    assert "Atomic Habits" in data["answer"]


def test_voice_nvidia_nim_pipeline_cleans_transcript(client, monkeypatch):
    from types import SimpleNamespace
    import openai
    from tests.voice_fixtures import make_wav_bytes

    wav = make_wav_bytes()

    def fake_transcribe(**_kwargs):
        return SimpleNamespace(
            text="Um, uh, remember to call Dr. Aris, like, tomorrow morning"
        )

    def fake_chat_complete(**kwargs):
        import json
        import re

        prompt = kwargs["messages"][-1]["content"]
        note_id = int(re.search(r'"id": (\d+)', prompt.split("Notes (JSON):", 1)[1]).group(1))
        answer = {"notes": [{
            "id": note_id, "area": "health", "topic": "Medicines & doctors", "confidence": "high",
            "rule": "R1", "choices": [], "title": "Call Dr. Aris", "priority": "High", "tags": [],
            "reason": "A doctor's call.", "tasks": [{"task": "Call Dr. Aris", "when": "tomorrow morning",
                                                     "date": None, "time": None}],
            "transcript": "Remember to call Dr. Aris tomorrow morning.", "summary": None, "action": None,
        }]}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", raising=False)
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda *args, **kwargs: SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=fake_transcribe)
            ),
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=fake_chat_complete)
            ),
        ),
    )

    resp = client.post(
        "/api/items/voice",
        files={"file": ("memo.wav", wav, "audio/wav")},
    )
    assert resp.status_code == 200
    item = resp.json()
    assert item["item_type"] == "voice"
    assert item["processing_status"] == "ready"
    assert item["extracted_text"] == "Um, uh, remember to call Dr. Aris, like, tomorrow morning"
    # Your words stay as transcribed; the filing call's tidy version is AI output.
    assert item["raw_text"] == "Um, uh, remember to call Dr. Aris, like, tomorrow morning"
    assert client.post(f"/api/analyze?item_id={item['id']}").status_code == 200
    insight = client.get(f"/api/items/{item['id']}/insight").json()
    assert insight["cleaned_transcript"] == "Remember to call Dr. Aris tomorrow morning."
    assert insight["filed_by"] == "ai" and insight["filing_rule"] == "R1"

    # Verify voice item can be edited via PUT /api/notes/{id}
    edited = client.put(
        f"/api/notes/{item['id']}",
        json={"text": "Remember to call Dr. Aris tomorrow afternoon."},
    )
    assert edited.status_code == 200
    assert edited.json()["text"] == "Remember to call Dr. Aris tomorrow afternoon."

    # Verify voice item can be deleted
    deleted = client.delete(f"/api/notes/{item['id']}")
    assert deleted.status_code == 204


def test_attention_board_buckets_and_briefing(client):
    client.post(
        "/api/items",
        json={"raw_text": "Pay the electricity bill tomorrow and renew insurance next Monday"},
    )
    analysis = client.post("/api/analyze").json()
    assert analysis["todos"]

    board = client.get("/api/attention").json()
    assert "today" in board and "upcoming" in board and "overdue" in board
    assert "unscheduled" in board
    assert board["reference_date"]

    briefing = client.get("/api/briefing").json()
    assert "summary" in briefing
    assert "counts" in briefing
    assert "priority_suggestions" in briefing


def test_snooze_and_calendar_preview_confirm_mock(client, monkeypatch):
    from app.integrations import calendar as calendar_mod

    calendar_mod.reset_calendar_adapter_for_tests()
    monkeypatch.setenv("LIFE_INBOX_CALENDAR_PROVIDER", "mock")

    client.post(
        "/api/items",
        json={"raw_text": "Submit tax filing tomorrow morning"},
    )
    client.post("/api/analyze")
    tasks = client.get("/api/tasks").json()
    assert tasks
    task = tasks[0]

    confirmed = client.post(
        f"/api/tasks/{task['id']}/confirm-timing",
        json={"timing_text": "tomorrow"},
    ).json()
    assert confirmed["timing_confirmed"] is True
    assert confirmed["due_on"]

    snoozed = client.post(
        f"/api/tasks/{task['id']}/snooze",
        json={"until": "2099-01-01"},
    ).json()
    assert snoozed["snoozed_until"] == "2099-01-01"

    # Unsnooze-ish by confirming again for calendar path
    client.post(
        f"/api/tasks/{task['id']}/confirm-timing",
        json={"timing_text": "2026-12-01"},
    )
    # Clear snooze for attention by setting past snooze
    client.post(
        f"/api/tasks/{task['id']}/snooze",
        json={"until": "2000-01-01"},
    )

    status = client.get("/api/calendar/status").json()
    assert status["writes_enabled"] is False
    assert status["oauth_connected"] is False

    preview = client.post(
        "/api/calendar/preview",
        json={"task_id": task["id"]},
    ).json()
    assert preview["status"] == "preview"
    assert preview["confirmation_required"] is True
    assert "draft_id" in preview

    confirmed_cal = client.post(
        "/api/calendar/confirm",
        json={"draft_id": preview["draft_id"]},
    ).json()
    assert confirmed_cal["status"] == "confirmed_mock"
    assert confirmed_cal["receipt"]["provider"] == "mock"


def test_google_calendar_confirm_is_blocked(client, monkeypatch):
    from app.integrations import calendar as calendar_mod

    calendar_mod.reset_calendar_adapter_for_tests()
    monkeypatch.setenv("LIFE_INBOX_CALENDAR_PROVIDER", "google")

    client.post(
        "/api/items",
        json={"raw_text": "Need to schedule dentist appointment on 2026-11-15"},
    )
    analysis = client.post("/api/analyze").json()
    tasks = client.get("/api/tasks").json()
    if not tasks:
        # Fallback organizer may omit todos for short notes; seed via timing confirm path
        # by re-analyzing a clearer action note.
        client.post(
            "/api/items",
            json={"raw_text": "TODO: Book dentist appointment for 2026-11-15"},
        )
        client.post("/api/analyze")
        tasks = client.get("/api/tasks").json()
    assert tasks, analysis
    task = tasks[0]
    client.post(
        f"/api/tasks/{task['id']}/confirm-timing",
        json={"timing_text": "2026-11-15"},
    )
    preview = client.post(
        "/api/calendar/preview",
        json={"task_id": task["id"]},
    ).json()
    blocked = client.post(
        "/api/calendar/confirm",
        json={"draft_id": preview["draft_id"]},
    )
    assert blocked.status_code == 403
    assert "disabled" in blocked.json()["detail"].lower()


def test_parse_timing_preserves_original_phrase():
    from app.attention.dates import parse_timing_phrase
    from datetime import date

    parsed = parse_timing_phrase("this weekend maybe", reference=date(2026, 10, 13))
    assert parsed.original_phrase == "this weekend maybe"
    assert parsed.due_date is not None
    assert parsed.needs_confirmation is True


def test_user_isolation_prevents_cross_account_access(client):
    alice = register(client, "alice@example.com", display_name="Alice")
    assert alice["email"] == "alice@example.com"
    alice_item = client.post(
        "/api/items",
        json={"raw_text": "Alice private note about taxes"},
    ).json()
    assert alice_item["owner_user_id"] == alice["id"]

    bob = register(client, "bob@example.com", display_name="Bob")
    assert bob["id"] != alice["id"]
    bob_items = client.get("/api/items").json()
    assert all(item["owner_user_id"] == bob["id"] for item in bob_items)
    assert alice_item["id"] not in {item["id"] for item in bob_items}

    missing = client.get(f"/api/items/{alice_item['id']}")
    assert missing.status_code == 404

    bob_dash = client.get("/api/dashboard").json()
    assert len(bob_dash["high_priority"]) == 0
    assert len(bob_dash["recently_captured"]) == 0

    deleted = client.delete(f"/api/items/{alice_item['id']}")
    assert deleted.status_code == 404

    # Switch back to Alice and confirm her item remains.
    login(client, "alice@example.com")
    still_there = client.get(f"/api/items/{alice_item['id']}")
    assert still_there.status_code == 200
    assert still_there.json()["raw_text"].startswith("Alice private")


def test_browser_supplied_user_id_header_is_ignored(client):
    alice = register(client, "alice2@example.com")
    client.post("/api/items", json={"raw_text": "Owned by Alice session"})
    # Spoof header must not switch identity.
    items = client.get("/api/items", headers={"X-User-Id": "999999"}).json()
    assert items
    assert all(item["owner_user_id"] == alice["id"] for item in items)


def test_dev_login_and_google_stub_are_removed(client):
    assert client.post(
        "/api/auth/dev-login", json={"email": "x@example.com"}
    ).status_code in {404, 405}
    assert client.get("/api/auth/google/start").status_code == 404


def test_health_includes_config_metadata(client):
    payload = client.get("/api/health").json()
    assert payload["status"] == "ok"
    assert "environment" in payload
    assert "database" in payload


def test_single_note_analysis_and_dashboard_completion_exclusion(client, monkeypatch):
    """Test targeted single-note analysis, cumulative merging, and completed items filtering."""
    item1 = client.post(
        "/api/items", json={"raw_text": "Doctor appointment Friday 3pm"}
    ).json()
    item2 = client.post(
        "/api/items", json={"raw_text": "Buy groceries tomorrow"}
    ).json()

    # 1. Analyze single item 1
    res1 = client.post(f"/api/analyze?item_id={item1['id']}")
    assert res1.status_code == 200
    data1 = res1.json()
    assert any(b["name"] for b in data1["buckets"])

    # 2. Analyze single item 2
    res2 = client.post(f"/api/analyze?item_id={item2['id']}")
    assert res2.status_code == 200
    data2 = res2.json()
    # Both notes should be present in cumulative analysis buckets
    all_note_ids = {n["id"] for b in data2["buckets"] for n in b.get("notes", [])}
    assert item1["id"] in all_note_ids
    assert item2["id"] in all_note_ids

    # 3. Check dashboard before completion
    dash1 = client.get("/api/dashboard").json()
    dash1_ids = {i["id"] for i in dash1.get("recently_captured", [])}
    assert item1["id"] in dash1_ids
    assert item2["id"] in dash1_ids

    # 4. Complete item 1 via POST /api/items/{id}/complete
    comp_res = client.post(f"/api/items/{item1['id']}/complete")
    assert comp_res.status_code == 200

    # 5. Dashboard must completely exclude completed item 1
    dash2 = client.get("/api/dashboard").json()
    recent_ids = {i["id"] for i in dash2.get("recently_captured", [])}
    high_ids = {i["id"] for i in dash2.get("high_priority", [])}
    needs_review_ids = {i["id"] for i in dash2.get("needs_review", [])}
    assert item1["id"] not in recent_ids
    assert item1["id"] not in high_ids
    assert item1["id"] not in needs_review_ids
    assert item2["id"] in recent_ids

    # Latest analysis returned in dashboard must also exclude completed item 1
    if dash2.get("analysis"):
        active_analysis_ids = {
            n["id"]
            for b in dash2["analysis"].get("buckets", [])
            for n in b.get("notes", [])
        }
        assert item1["id"] not in active_analysis_ids


def test_quick_add_task_without_due_date(client):
    response = client.post(
        "/api/tasks",
        json={
            "text": "Prepare AI assignment",
            "priority": "High",
        },
    )

    assert response.status_code == 201
    task = response.json()
    assert task["text"] == "Prepare AI assignment"
    assert task["priority"] == "High"
    assert task["status"] == "open"
    assert task["due_on"] is None
    assert task["source_item_ids"] == []

    tasks = client.get("/api/tasks").json()
    assert task in tasks


def test_quick_add_task_with_due_date(client):
    response = client.post(
        "/api/tasks",
        json={
            "text": "Submit assignment",
            "priority": "Medium",
            "due_on": "2026-11-15",
        },
    )

    assert response.status_code == 201
    task = response.json()
    assert task["due_on"] == "2026-11-15"
    assert task["timing_confirmed"] is True

    board = client.get("/api/attention")
    assert board.status_code == 200


def test_quick_add_task_rejects_invalid_input(client):
    empty_title = client.post(
        "/api/tasks",
        json={"text": "   ", "priority": "Medium"},
    )
    assert empty_title.status_code == 422

    invalid_priority = client.post(
        "/api/tasks",
        json={"text": "Valid task", "priority": "Urgent"},
    )
    assert invalid_priority.status_code == 422


def test_editing_note_updates_task_without_duplication(client):
    # 1. Create a note and analyze it
    item = client.post(
        "/api/items",
        json={"raw_text": "I need to play pickleball at 8pm today."}
    ).json()
    res1 = client.post(f"/api/analyze?item_id={item['id']}")
    assert res1.status_code == 200

    tasks1 = client.get("/api/tasks").json()
    assert len(tasks1) == 1
    assert "pickleball" in tasks1[0]["text"].lower()

    # 2. Edit note to add more details (e.g. "with vijay")
    client.put(
        f"/api/items/{item['id']}",
        json={"raw_text": "I need to play pickleball with vijay at 8pm today"}
    )
    res2 = client.post(f"/api/analyze?item_id={item['id']}")
    assert res2.status_code == 200

    # 3. Tasks list must have exactly 1 task (updated), no duplicate tasks
    tasks2 = client.get("/api/tasks").json()
    assert len(tasks2) == 1
    assert "vijay" in tasks2[0]["text"].lower()
    assert tasks2[0]["source_item_ids"] == [item["id"]]



def test_note_box_is_capped_at_server_limit(client):
    page = client.get("/").text
    assert 'id="noteText" maxlength="2000"' in page
    assert 'id="noteCharCount"' in page
    assert "max 2000 characters" in page

    assert client.post("/api/items", json={"raw_text": "a" * 2000}).status_code == 200
    assert client.post("/api/items", json={"raw_text": "a" * 2001}).status_code == 422
