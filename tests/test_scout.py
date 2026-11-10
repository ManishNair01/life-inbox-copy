"""Change 018: Scout, the catch-up helper (no AI call anywhere).

Triggers with a fixed clock (the day after a date, the weekly catch-up, after
a break, stale Someday items), each answer and its effects (task events,
memory), the bulk actions, Someday staying off dates and questions, and the
weekly push going through the existing dispatcher."""

import importlib
import sys
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer", "app.scout")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'scout.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("LIFE_INBOX_TIMEZONE", raising=False)
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


def as_owner(client):
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    return database


def scout():
    return importlib.import_module("app.scout")


def now_local():
    return scout()._local_now()


def today():
    return now_local().date()


def make_task(client, text, days=None, time=None):
    task = client.post("/api/tasks", json={"text": text}).json()
    if days is not None:
        body = {"due_on": (today() + timedelta(days=days)).isoformat(), **({"due_time": time} if time else {})}
        assert client.post(f"/api/tasks/{task['id']}/date", json=body).status_code == 200
    return task


def age_task(database, task_id, days, someday_days=None):
    """Make a task look older (created days ago; someday since someday_days ago)."""
    with database.SessionLocal() as session:
        row = session.get(database.TaskRecord, task_id)
        row.created_at = (datetime.now(now_local().tzinfo) - timedelta(days=days)).isoformat()
        if someday_days is not None:
            row.someday, row.someday_since = 1, (datetime.now(now_local().tzinfo) - timedelta(days=someday_days)).isoformat()
        session.commit()


def set_settings(database, **values):
    owner = database.require_owner_id()
    database.get_settings(owner)
    with database.SessionLocal() as session:
        row = session.get(database.UserSettingsRecord, owner)
        for key, value in values.items():
            setattr(row, key, value)
        session.commit()


def events(database):
    with database.SessionLocal() as session:
        return [(row.task_id, row.kind, row.by, row.reason) for row in
                session.query(database.TaskEventRecord).order_by(database.TaskEventRecord.id)]


# --- when Scout asks -----------------------------------------------------------------------


def test_the_catchup_slot_is_the_last_sunday_evening():
    slot = importlib.import_module("app.scout").catchup_slot
    settings = {"catchup_day": "sun", "catchup_time": "19:00"}
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("UTC")
    sunday_before = datetime(2026, 11, 15, 18, 0, tzinfo=zone)   # Sunday 18:00
    sunday_after = datetime(2026, 11, 15, 19, 30, tzinfo=zone)   # Sunday 19:30
    wednesday = datetime(2026, 11, 18, 9, 0, tzinfo=zone)
    assert slot(settings, sunday_before) == datetime(2026, 11, 8, 19, 0, tzinfo=zone)
    assert slot(settings, sunday_after) == datetime(2026, 11, 15, 19, 0, tzinfo=zone)
    assert slot(settings, wednesday) == datetime(2026, 11, 15, 19, 0, tzinfo=zone)
    assert slot({"catchup_day": "sat", "catchup_time": "08:30"}, wednesday) == datetime(2026, 11, 14, 8, 30, tzinfo=zone)


def test_the_day_after_a_task_date_scout_asks(client):
    yesterday = make_task(client, "Python quiz", days=-1)
    make_task(client, "Call the plumber", days=0)
    make_task(client, "Pay rent", days=3)
    state = client.get("/api/scout").json()
    assert [q["task_id"] for q in state["questions"]] == [yesterday["id"]]
    question = state["questions"][0]
    assert question["kind"] == "past" and "Did you do it?" in question["text"]
    assert [a["action"] for a in question["actions"]] == ["done", "reschedule", "drop"]


def test_the_weekly_catchup_adds_old_undated_tasks_and_waits_for_a_new_account(client):
    database = as_owner(client)
    old = make_task(client, "Fix the bike")
    age_task(database, old["id"], 20)
    fixed_now = now_local()
    # A brand-new account waits for its first catch-up.
    assert client.get("/api/scout").json()["mode"] == "daily"
    set_settings(database, created_at=(fixed_now - timedelta(days=30)).isoformat())
    state = scout().state(now=fixed_now)
    assert state["mode"] == "weekly" and state["catchup_due"]
    assert state["intro"] == "Let's tidy up: 1 quick question."
    assert [(q["kind"], q["task_id"]) for q in state["questions"]] == [("undated", old["id"])]
    finished = client.post("/api/scout/finish").json()
    assert finished["mode"] == "daily" and not finished["catchup_due"]
    assert finished["questions"] == []  # outside a catch-up, undated tasks don't ask


def test_after_a_break_scout_offers_a_catchup(client):
    database = as_owner(client)
    make_task(client, "Renew passport", days=-2)
    set_settings(database, last_seen_at=(now_local() - timedelta(days=9)).isoformat(),
                 created_at=(now_local() - timedelta(days=60)).isoformat(),
                 last_catchup_at=now_local().isoformat())
    state = client.get("/api/scout").json()
    assert state["mode"] == "away" and state["away_days"] == 9
    assert state["intro"].startswith("You've been away 9 days. A 1-minute catch-up?")
    assert client.get("/api/scout").json()["mode"] == "away"  # stays until you finish
    client.post("/api/scout/finish")
    assert client.get("/api/scout").json()["mode"] == "daily"


def test_at_most_ten_questions_at_a_time(client):
    for number in range(13):
        make_task(client, f"Old thing {number}", days=-1 - number)
    state = client.get("/api/scout").json()
    assert len(state["questions"]) == 10 and state["total"] == 13
    days = [q["data"]["due_on"] for q in state["questions"]]
    assert days == sorted(days, reverse=True)  # yesterday first


def test_stale_someday_tasks_are_asked_monthly(client):
    database = as_owner(client)
    task = make_task(client, "Learn the ukulele")
    age_task(database, task["id"], 60, someday_days=35)
    set_settings(database, created_at=(now_local() - timedelta(days=60)).isoformat())
    state = scout().state(now=now_local())
    [question] = [q for q in state["questions"] if q["kind"] == "someday"]
    assert [a["action"] for a in question["actions"]] == ["keep", "reschedule", "drop"]
    result = client.post(f"/api/scout/{question['id']}/answer", json={"action": "keep"}).json()
    assert result["said"] == "Kept on your Someday list."
    assert all(q["kind"] != "someday" for q in scout().state(now=now_local())["questions"])


# --- answers -------------------------------------------------------------------------------


def test_done_completes_the_task_and_updates_memory(client):
    database = as_owner(client)
    note = client.post("/api/items", json={"raw_text": "Python quiz on Tuesday"}).json()
    client.post("/api/analyze", params={"item_id": note["id"]})
    [task] = client.get("/api/tasks?status=open").json()
    client.post(f"/api/tasks/{task['id']}/date", json={"due_on": (today() - timedelta(days=1)).isoformat()})
    [question] = client.get("/api/scout").json()["questions"]

    result = client.post(f"/api/scout/{question['id']}/answer", json={"action": "done"}).json()
    assert result["said"].startswith("Captain updated the Learning & work bot's memory: ")
    assert result["said"].endswith(": done.")
    assert client.get("/api/tasks?status=open").json() == []
    assert (task["id"], "done", "scout", None) in events(database)
    facts = client.get("/api/memory?bot=learn").json()["facts"]
    assert any(f["kind"] == "short_term" and f["source_kind"] == "scout" and f["text"].endswith(": done.") for f in facts)
    # Answered: the same question can't be answered twice.
    assert client.post(f"/api/scout/{question['id']}/answer", json={"action": "done"}).status_code == 409


def test_a_new_date_moves_it_and_drop_keeps_your_reason(client):
    database = as_owner(client)
    first = make_task(client, "Dentist", days=-1)
    second = make_task(client, "Buy a kettle", days=-2)
    questions = {q["task_id"]: q for q in client.get("/api/scout").json()["questions"]}
    new_day = (today() + timedelta(days=4)).isoformat()

    assert client.post(f"/api/scout/{questions[first['id']]['id']}/answer", json={"action": "reschedule"}).status_code == 422
    moved = client.post(f"/api/scout/{questions[first['id']]['id']}/answer",
                        json={"action": "reschedule", "due_on": new_day, "due_time": "16:00"}).json()
    assert "moved to" in moved["said"]
    dentist = next(t for t in client.get("/api/tasks?status=open").json() if t["id"] == first["id"])
    assert (dentist["due_on"], dentist["due_time"], dentist["timing_confirmed"]) == (new_day, "16:00", True)

    client.post(f"/api/scout/{questions[second['id']]['id']}/answer", json={"action": "drop", "reason": "Someone else did it"})
    assert [t["id"] for t in client.get("/api/tasks?status=open").json()] == [first["id"]]
    assert (second["id"], "dropped", "scout", "Someone else did it") in events(database)
    assert (first["id"], "rescheduled", "scout", None) in events(database)


def test_skip_and_wrong_answers(client):
    task = make_task(client, "Water the plants", days=-1)
    [question] = client.get("/api/scout").json()["questions"]
    assert client.post(f"/api/scout/{question['id']}/answer", json={"action": "keep"}).status_code == 422
    assert client.post(f"/api/scout/{question['id']}/answer", json={"action": "bogus"}).status_code == 422
    skipped = client.post(f"/api/scout/{question['id']}/answer", json={"action": "skip"}).json()
    assert skipped["scout"]["questions"] == []
    assert [t["id"] for t in client.get("/api/tasks?status=open").json()] == [task["id"]]  # unchanged


def test_your_own_actions_are_task_events_too(client):
    database = as_owner(client)
    task = make_task(client, "Send the form")
    client.post(f"/api/tasks/{task['id']}/complete")
    client.post(f"/api/tasks/{task['id']}/reopen")
    kinds = [(kind, by) for task_id, kind, by, _ in events(database) if task_id == task["id"]]
    assert kinds == [("done", "you"), ("reopened", "you")]


# --- bulk actions and Someday ---------------------------------------------------------------------


def test_bulk_moves_old_tasks_to_someday_and_past_tasks_to_next_week(client):
    database = as_owner(client)
    old = make_task(client, "Sort the photos")
    age_task(database, old["id"], 40)
    past = make_task(client, "Return the book", days=-3)
    plan = client.get("/api/scout").json()["bulk"]
    assert plan == {"old_to_someday": [old["id"]], "past_to_next_week": [past["id"]]}

    result = client.post("/api/scout/bulk", json={"which": "old_to_someday"}).json()
    assert result["said"] == "Moved 1 task to Someday." and result["moved"] == [old["id"]]
    result = client.post("/api/scout/bulk", json={"which": "past_to_next_week"}).json()
    monday = scout().next_week(now_local())
    assert result["said"].startswith("Moved 1 task to Mon ")
    tasks = {t["id"]: t for t in client.get("/api/tasks?status=open").json()}
    assert tasks[old["id"]]["someday"] is True and tasks[old["id"]]["due_on"] is None
    assert tasks[past["id"]]["due_on"] == monday
    assert client.post("/api/scout/bulk", json={"which": "everything"}).status_code == 422


def test_someday_tasks_leave_dates_and_questions(client):
    task = make_task(client, "Call the bank", days=2)
    response = client.post(f"/api/tasks/{task['id']}/someday", json={"someday": True})
    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["someday"] is True and moved["due_on"] is None and moved["suggested_due_on"] is None
    start = today().isoformat()
    end = (today() + timedelta(days=7)).isoformat()
    events_json = client.get("/api/calendar/events", params={"start": start, "end": end}).json()
    assert all(event.get("task_id") != task["id"] for event in (events_json if isinstance(events_json, list) else events_json.get("events", [])))
    needs = client.get("/api/captain/needs-you").json()["cards"]
    assert all(card.get("task_id") != task["id"] for card in needs)  # no "No date yet" card
    back = client.post(f"/api/tasks/{task['id']}/someday", json={"someday": False}).json()
    assert back["someday"] is False
    assert client.post("/api/tasks/9999/someday", json={"someday": True}).status_code == 404


# --- push, through the existing dispatcher -------------------------------------------------------


def test_the_weekly_push_goes_through_the_dispatcher_once_per_slot(monkeypatch):
    from zoneinfo import ZoneInfo

    from app.notifications import service

    monkeypatch.setenv("LIFE_INBOX_VAPID_PUBLIC_KEY", "public")
    monkeypatch.setenv("LIFE_INBOX_VAPID_PRIVATE_KEY", "private")
    sunday_evening = datetime(2026, 11, 15, 19, 30, tzinfo=ZoneInfo("UTC"))
    user = {"user_id": 5, "daily_digest_time": "23:59", "timezone": "UTC", "include_unscheduled_prompt": False,
            "catchup_day": "sun", "catchup_time": "19:00", "last_catchup_at": None,
            "created_at": "2026-10-01T10:00:00+00:00", "away_days": None}
    tasks = [{"id": 1, "text": "Quiz", "priority": "Medium", "due_on": "2026-11-12", "due_time": None,
              "timing_text": None, "timing_confirmed": True, "ai_generated": False, "snoozed_until": None,
              "someday": False}]
    claimed, sent = set(), []

    def claim(**kwargs):
        if kwargs["idempotency_key"] in claimed:
            return False
        claimed.add(kwargs["idempotency_key"])
        return True

    monkeypatch.setattr(service, "list_notification_users", lambda: [user])
    monkeypatch.setattr(service, "list_notification_tasks", lambda user_id: tasks)
    monkeypatch.setattr(service, "list_push_subscriptions", lambda user_id: [{"id": 1, "endpoint": "https://push.example.test"}])
    monkeypatch.setattr(service, "claim_notification_delivery", claim)
    monkeypatch.setattr(service, "finish_notification_delivery", lambda key, **kwargs: None)
    monkeypatch.setattr(service, "_send_push", lambda subscription, payload: sent.append(payload))

    assert service.dispatch_due_notifications(sunday_evening) == {"sent": 1, "skipped": 0, "failed": 0}
    assert sent[0]["title"] == "Scout · your weekly catch-up" and sent[0]["url"] == "/#/scout"
    assert "1 task whose day has passed" in sent[0]["body"]
    assert "scout:5:2026-11-15" in claimed
    service.dispatch_due_notifications(sunday_evening + timedelta(minutes=5))
    assert len(sent) == 1  # once per catch-up slot

    # Nothing past due, or the catch-up already done: no push.
    sent.clear()
    claimed.clear()
    user["last_catchup_at"] = "2026-11-15T19:10:00+00:00"
    service.dispatch_due_notifications(sunday_evening)
    assert sent == []
