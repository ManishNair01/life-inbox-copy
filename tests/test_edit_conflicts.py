"""Optimistic concurrency for item edits (same user, two tabs or devices)."""

import sys
import threading

from fastapi.testclient import TestClient

from tests.test_api import client  # noqa: F401  (fixture: isolated temp DB)
from tests.voice_fixtures import make_wav_bytes


def _new_item(http, text="First draft"):
    response = http.post("/api/items", json={"raw_text": text})
    assert response.status_code == 200, response.text
    return response.json()


def test_new_items_start_at_version_one_and_edits_increment(client):  # noqa: F811
    item = _new_item(client)
    assert item["version"] == 1

    edited = client.put(
        f"/api/items/{item['id']}",
        json={"raw_text": "Second", "expected_version": 1},
    )
    assert edited.status_code == 200
    assert edited.json()["version"] == 2
    assert client.get(f"/api/items/{item['id']}").json()["version"] == 2


def test_stale_edit_is_rejected_with_current_item(client):  # noqa: F811
    item = _new_item(client)
    first = client.put(
        f"/api/items/{item['id']}",
        json={"raw_text": "Tab A wins", "expected_version": 1},
    )
    assert first.status_code == 200

    stale = client.put(
        f"/api/items/{item['id']}",
        json={"raw_text": "Tab B is stale", "expected_version": 1},
    )

    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "version_conflict"
    assert detail["current"]["raw_text"] == "Tab A wins"
    assert detail["current"]["version"] == 2
    assert client.get(f"/api/items/{item['id']}").json()["raw_text"] == "Tab A wins"


def test_retrying_with_the_current_version_overwrites_deliberately(client):  # noqa: F811
    item = _new_item(client)
    client.put(f"/api/items/{item['id']}", json={"raw_text": "A", "expected_version": 1})
    stale = client.put(
        f"/api/items/{item['id']}", json={"raw_text": "B", "expected_version": 1}
    )
    current = stale.json()["detail"]["current"]["version"]

    retry = client.put(
        f"/api/items/{item['id']}",
        json={"raw_text": "B", "expected_version": current},
    )

    assert retry.status_code == 200
    assert retry.json()["raw_text"] == "B"
    assert retry.json()["version"] == 3


def test_edit_without_expected_version_is_last_write_wins_but_bumps(client):  # noqa: F811
    item = _new_item(client)
    client.put(f"/api/items/{item['id']}", json={"raw_text": "A", "expected_version": 1})

    legacy = client.put(f"/api/items/{item['id']}", json={"raw_text": "Legacy"})

    assert legacy.status_code == 200
    assert legacy.json()["raw_text"] == "Legacy"
    assert legacy.json()["version"] == 3


def test_deprecated_notes_endpoint_still_edits_and_bumps_version(client):  # noqa: F811
    item = _new_item(client)
    assert client.put(f"/api/notes/{item['id']}", json={"text": "Via notes"}).status_code == 200
    assert client.get(f"/api/items/{item['id']}").json()["version"] == 2


def test_two_simultaneous_edits_from_same_version_one_wins(client):  # noqa: F811
    app = sys.modules["app.main"].app
    item = _new_item(client)
    barrier = threading.Barrier(2)
    statuses = []

    def edit(label):
        with TestClient(app) as http:
            barrier.wait()
            response = http.put(
                f"/api/items/{item['id']}",
                json={"raw_text": f"edit {label}", "expected_version": 1},
            )
            statuses.append(response.status_code)

    threads = [threading.Thread(target=edit, args=(n,)) for n in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(statuses) == [200, 409]
    assert client.get(f"/api/items/{item['id']}").json()["version"] == 2


def test_background_text_changes_also_bump_the_version(client):  # noqa: F811
    from app import database

    item = _new_item(client)
    with database.SessionLocal() as session:
        row = session.get(database.InboxItemRecord, item["id"])
        row.raw_text = "Rewritten by processing"
        session.commit()

    stale = client.put(
        f"/api/items/{item['id']}",
        json={"raw_text": "Edit from old copy", "expected_version": 1},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["raw_text"] == "Rewritten by processing"


def test_non_text_updates_do_not_bump_the_version(client):  # noqa: F811
    from app import database

    item = _new_item(client)
    with database.SessionLocal() as session:
        row = session.get(database.InboxItemRecord, item["id"])
        row.error_message = "transient"
        session.commit()

    assert client.get(f"/api/items/{item['id']}").json()["version"] == 1


def test_extracted_text_edits_use_the_same_version_check(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", "1")
    voice = client.post(
        "/api/items/voice",
        files={"file": ("memo.wav", make_wav_bytes(), "audio/wav")},
    )
    assert voice.status_code in (200, 201), voice.text
    item = voice.json()
    url = f"/api/items/{item['id']}/extracted-text"

    first = client.patch(
        url, json={"extracted_text": "Transcript v2", "expected_version": item["version"]}
    )
    assert first.status_code == 200
    assert first.json()["version"] == item["version"] + 1

    stale = client.patch(
        url, json={"extracted_text": "Stale", "expected_version": item["version"]}
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["extracted_text"] == "Transcript v2"


def test_extracted_text_edit_cannot_touch_another_users_item(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", "1")
    client.post("/api/auth/dev-login", json={"email": "owner-ev@example.com"})
    voice = client.post(
        "/api/items/voice",
        files={"file": ("memo.wav", make_wav_bytes(), "audio/wav")},
    ).json()

    client.post("/api/auth/dev-login", json={"email": "intruder-ev@example.com"})
    from app import database

    assert database.update_item_extracted_text(voice["id"], "hijack") is None
    response = client.patch(
        f"/api/items/{voice['id']}/extracted-text", json={"extracted_text": "hijack"}
    )
    assert response.status_code == 404
