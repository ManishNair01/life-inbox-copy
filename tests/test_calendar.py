import importlib
import sys
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import login, register

# Notes below say e.g. "3 Nov {YEAR}" with an explicit year. A bare "3 Nov" is
# read as the *next* occurrence, so these tests used to fail every year once
# that date had passed. Next year is always in the future, whatever today is.
YEAR = date.today().year + 1


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Create an app client backed only by a per-test SQLite database."""
    test_db_path = tmp_path / "life_inbox_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_TIMEZONE", "Asia/Kolkata")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)

    for module_name in (
        "app.main",
        "app.database",
        "app.auth",
        "app.config",
        "app.attention.dates",
        "app.integrations.calendar",
    ):
        sys.modules.pop(module_name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    # These tests use fixed November 2026 dates ("dentist on 3 Nov"). Pin
    # "today" so they keep meaning this November: after 3 Nov the date reader
    # rightly reads "3 Nov" as next year.
    monkeypatch.setattr(
        importlib.import_module("app.attention.dates"),
        "today_in_configured_tz",
        lambda: date(2026, 11, 2),
    )
    # Change 012 reads a note's dates from the day it was written, so pin
    # that day too: these notes count as written on 2 Nov 2026.
    monkeypatch.setattr(database, "_written_day", lambda session, item_ids: date(2026, 11, 2))

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
        "app.attention.dates",
        "app.integrations.calendar",
    ):
        sys.modules.pop(module_name, None)


def test_calendar_events_validation(client):
    # Missing parameters
    res = client.get("/api/calendar/events")
    assert res.status_code == 422

    # Malformed date format
    res = client.get("/api/calendar/events?start=invalid&end=2026-11-30")
    assert res.status_code == 400
    assert "YYYY-MM-DD" in res.json()["detail"]

    # Start date after end date
    res = client.get("/api/calendar/events?start=2026-12-01&end=2026-11-01")
    assert res.status_code == 400
    assert "must not be after" in res.json()["detail"]


def test_calendar_events_date_range_and_undated_exclusion(client):
    # Note 1: dated inside November range
    item1 = client.post("/api/items", json={"raw_text": f"dentist on 3 Nov {YEAR}"}).json()
    # Note 2: dated in December (outside November query)
    item2 = client.post("/api/items", json={"raw_text": f"buy flight tickets on 15 Dec {YEAR}"}).json()
    # Note 3: completely undated note
    item3 = client.post("/api/items", json={"raw_text": "random thoughts on system design without any date"}).json()

    # Trigger analysis
    analyze_res = client.post("/api/analyze")
    assert analyze_res.status_code == 200

    # Query for November of the test year
    events_res = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30")
    assert events_res.status_code == 200
    events = events_res.json()

    # Only note 1 should be returned
    assert len(events) == 1
    ev = events[0]
    assert ev["event_date"] == f"{YEAR}-11-03"
    assert "dentist" in ev["title"].lower()
    assert ev["source_item_id"] == item1["id"]
    assert ev["source_type"] == "text"
    assert ev["status"] == "open"

    # Query for December of the test year
    dec_events_res = client.get(f"/api/calendar/events?start={YEAR}-12-01&end={YEAR}-12-31")
    assert dec_events_res.status_code == 200
    dec_events = dec_events_res.json()
    assert len(dec_events) == 1
    assert dec_events[0]["event_date"] == f"{YEAR}-12-15"
    assert dec_events[0]["source_item_id"] == item2["id"]

    # Undated item3 is never returned
    all_events_res = client.get(f"/api/calendar/events?start={YEAR - 1}-01-01&end={YEAR + 1}-12-31")
    all_source_ids = {e["source_item_id"] for e in all_events_res.json()}
    assert item3["id"] not in all_source_ids


def test_calendar_events_user_isolation(client):
    # Alice logs in and saves a dated note
    alice = register(client, "alice@calendar.test", display_name="Alice")
    alice_item = client.post("/api/items", json={"raw_text": f"dentist on 3 Nov {YEAR}"}).json()
    client.post("/api/analyze")

    alice_events = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(alice_events) == 1
    assert alice_events[0]["source_item_id"] == alice_item["id"]

    # Bob logs in
    bob = register(client, "bob@calendar.test", display_name="Bob")
    assert bob["id"] != alice["id"]

    # Bob's calendar should be completely empty
    bob_events = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(bob_events) == 0

    # Bob adds his own event
    bob_item = client.post("/api/items", json={"raw_text": f"team sync on 10 Nov {YEAR}"}).json()
    client.post("/api/analyze")

    bob_events2 = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(bob_events2) == 1
    assert bob_events2[0]["source_item_id"] == bob_item["id"]
    assert bob_events2[0]["source_item_id"] != alice_item["id"]


def test_calendar_events_ambiguous_and_confirmed_dates(client):
    # "renew insurance by next Friday" is a guess (change 012): it waits for
    # your OK as a suggestion and stays off the calendar until you confirm it.
    item = client.post("/api/items", json={"raw_text": "renew insurance by next Friday"}).json()
    client.post("/api/analyze")

    from app.attention.dates import parse_timing_phrase
    parsed = parse_timing_phrase("next Friday")
    assert parsed.due_date is not None
    due_iso = parsed.due_date.isoformat()

    assert client.get(f"/api/calendar/events?start={due_iso}&end={due_iso}").json() == []
    task = next(t for t in client.get("/api/tasks").json() if item["id"] in t["source_item_ids"])
    assert task["due_on"] is None and task["suggested_due_on"] == due_iso
    assert task["due_confidence"] == "suggested"

    # Confirm a different day via the tasks API: it goes on the calendar, confirmed.
    confirm_res = client.post(
        f"/api/tasks/{task['id']}/confirm-timing",
        json={"timing_text": f"{YEAR}-11-20"},
    )
    assert confirm_res.status_code == 200

    # Event now has timing_confirmed=True and needs_confirmation=False on the confirmed date
    updated_events = client.get(f"/api/calendar/events?start={YEAR}-11-20&end={YEAR}-11-20").json()
    assert len(updated_events) == 1
    assert updated_events[0]["timing_confirmed"] is True
    assert updated_events[0]["needs_confirmation"] is False
    assert updated_events[0]["event_date"] == f"{YEAR}-11-20"


def test_calendar_events_completed_and_dismissed_statuses(client):
    item = client.post("/api/items", json={"raw_text": f"dentist on 3 Nov {YEAR}"}).json()
    client.post("/api/analyze")

    events = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(events) == 1
    task_id = events[0]["id"]
    assert events[0]["status"] == "open"

    # Complete the task
    complete_res = client.post(f"/api/tasks/{task_id}/complete")
    assert complete_res.status_code == 200

    # Event is still on calendar but status is "completed"
    events_after_complete = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(events_after_complete) == 1
    assert events_after_complete[0]["status"] == "completed"

    # Dismiss the task
    dismiss_res = client.post(f"/api/tasks/{task_id}/dismiss")
    assert dismiss_res.status_code == 200

    # Dismissed task is excluded from calendar view
    events_after_dismiss = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(events_after_dismiss) == 0


def test_calendar_events_note_edit_and_delete_lifecycle(client):
    item = client.post("/api/items", json={"raw_text": f"dentist on 3 Nov {YEAR}"}).json()
    client.post("/api/analyze")

    events = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(events) == 1
    assert events[0]["event_date"] == f"{YEAR}-11-03"

    # Edit note text to change date to 10 Nov
    client.put(f"/api/items/{item['id']}", json={"raw_text": f"dentist on 10 Nov {YEAR}"})
    client.post("/api/analyze")

    events_after_edit = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(events_after_edit) == 1
    assert events_after_edit[0]["event_date"] == f"{YEAR}-11-10"

    # Delete the note
    delete_res = client.delete(f"/api/items/{item['id']}")
    assert delete_res.status_code == 204

    # Orphan task is deleted; calendar has no events
    events_after_delete = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    assert len(events_after_delete) == 0


def test_calendar_html_elements_present(client):
    res = client.get("/")
    assert res.status_code == 200
    html = res.text
    assert 'id="inAppCalendar"' in html
    assert 'id="calendarGrid"' in html
    assert 'id="calendarDayHeading"' in html
    assert 'id="calendarEventsList"' in html
    assert 'id="calPrevBtn"' in html
    assert 'id="calNextBtn"' in html
    assert 'id="calTodayBtn"' in html


def test_calendar_events_different_source_types(client, monkeypatch):
    from tests.image_fixtures import make_png_bytes

    monkeypatch.setenv("LIFE_INBOX_DISABLE_OCR", "1")

    # Text note
    text_item = client.post("/api/items", json={"raw_text": f"Dentist appointment on 3 Nov {YEAR}"}).json()

    # Image saved with your note giving its date. Tasks (and so calendar
    # dates) come only from your own words, never from a source's text
    # (change 014), so the OCR'd date alone would not be enough.
    img_res = client.post(
        "/api/items/image",
        files={"file": ("receipt.png", make_png_bytes(), "image/png")},
        data={"context": f"My flight is on 18 Nov {YEAR}"},
    )
    assert img_res.status_code == 200
    img_item = img_res.json()
    assert img_item["processing_status"] == "ready"

    # Update extracted text to simulate OCR with date
    client.patch(
        f"/api/items/{img_item['id']}/extracted-text",
        json={"extracted_text": f"Flight ticket confirmation for 18 Nov {YEAR}"}
    )

    client.post("/api/analyze")

    events = client.get(f"/api/calendar/events?start={YEAR}-11-01&end={YEAR}-11-30").json()
    types_by_date = {e["event_date"]: e["source_type"] for e in events}
    assert types_by_date.get(f"{YEAR}-11-03") == "text"
    assert types_by_date.get(f"{YEAR}-11-18") == "image"

