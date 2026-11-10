from datetime import date, datetime, timezone

from app.notifications import service


def task(
    *,
    task_id=1,
    text="Finish report",
    priority="Medium",
    due_on="2026-10-26",
    due_time=None,
    timing_text=None,
    timing_confirmed=False,
    ai_generated=False,
    snoozed_until=None,
):
    return {
        "id": task_id,
        "text": text,
        "priority": priority,
        "due_on": due_on,
        "due_time": due_time,
        "timing_text": timing_text,
        "timing_confirmed": timing_confirmed,
        "ai_generated": ai_generated,
        "snoozed_until": snoozed_until,
    }


def test_daily_digest_contains_only_due_today_and_optional_unscheduled_count():
    payload = service._daily_payload(
        [
            task(text="Due today"),
            task(task_id=2, text="Overdue", due_on="2026-10-25"),
            task(task_id=3, text="Unscheduled", due_on=None),
        ],
        local_date=date(2026, 10, 26),
        unscheduled_count=2,
    )

    assert payload is not None
    assert "Due today" in payload["body"]
    assert "Overdue" not in payload["body"]
    assert "Unscheduled" not in payload["body"]
    assert "2 unscheduled task(s)" in payload["body"]


def test_daily_digest_skips_empty_day_without_unscheduled_prompt():
    payload = service._daily_payload(
        [task(due_on="2026-10-25")],
        local_date=date(2026, 10, 26),
        unscheduled_count=0,
    )

    assert payload is None


def test_one_hour_alert_requires_ai_high_task_and_explicit_unambiguous_time():
    eligible = task(
        priority="High",
        due_time="10:00",
        timing_text="2026-10-26 at 10am",
        ai_generated=True,
    )
    manual_high = task(
        task_id=2,
        priority="High",
        due_time="10:00",
        timing_text="2026-10-26 at 10am",
    )
    date_only = task(
        task_id=3,
        priority="High",
        timing_text="2026-10-26",
        ai_generated=True,
    )
    ambiguous = task(
        task_id=4,
        priority="High",
        due_time="10:00",
        timing_text="this weekend at 10am",
        ai_generated=True,
    )

    assert service._eligible_high_priority(eligible, "UTC") == datetime(
        2026, 10, 26, 10, tzinfo=timezone.utc
    )
    assert service._eligible_high_priority(manual_high, "UTC") is None
    assert service._eligible_high_priority(date_only, "UTC") is None
    assert service._eligible_high_priority(ambiguous, "UTC") is None


def test_one_hour_alert_skips_nonexistent_dst_local_time():
    spring_gap = task(
        priority="High",
        due_on="2026-03-08",
        due_time="02:30",
        timing_text="2026-03-08 at 2:30am",
        ai_generated=True,
    )

    assert (
        service._eligible_high_priority(spring_gap, "America/New_York")
        is None
    )


def test_dispatch_sends_daily_digest_and_one_hour_ai_high_alert(monkeypatch):
    monkeypatch.setenv("LIFE_INBOX_VAPID_PUBLIC_KEY", "public")
    monkeypatch.setenv("LIFE_INBOX_VAPID_PRIVATE_KEY", "private")
    ai_high = task(
        task_id=1,
        text="Submit the report",
        priority="High",
        due_time="10:00",
        timing_text="2026-10-26 at 10am",
        ai_generated=True,
    )
    manual_high = task(
        task_id=2,
        text="Book a table",
        priority="High",
        due_time="10:00",
        timing_text="2026-10-26 at 10am",
    )
    subscriptions = [{"id": 8, "endpoint": "https://push.example.test"}]
    sent = []
    finished = []

    monkeypatch.setattr(
        service, "list_notification_users",
        lambda: [{
            "user_id": 3,
            "daily_digest_time": "08:00",
            "timezone": "UTC",
            "include_unscheduled_prompt": False,
        }],
    )
    monkeypatch.setattr(
        service, "list_notification_tasks",
        lambda user_id: [ai_high, manual_high],
    )
    monkeypatch.setattr(
        service, "list_push_subscriptions",
        lambda user_id: subscriptions,
    )
    monkeypatch.setattr(
        service, "claim_notification_delivery",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        service, "finish_notification_delivery",
        lambda key, **kwargs: finished.append((key, kwargs)),
    )
    monkeypatch.setattr(
        service, "_send_push",
        lambda subscription, payload: sent.append(payload),
    )

    result = service.dispatch_due_notifications(
        datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
    )

    assert result == {"sent": 2, "skipped": 0, "failed": 0}
    assert len(sent) == 2
    assert any(payload["title"].startswith("Tasks for today") for payload in sent)
    assert any(
        payload["title"] == "High-priority task in one hour"
        and payload["task_id"] == 1
        for payload in sent
    )
    assert all(kwargs["delivered"] for _, kwargs in finished)


def test_dispatch_does_not_send_before_daily_digest_time(monkeypatch):
    monkeypatch.setenv("LIFE_INBOX_VAPID_PUBLIC_KEY", "public")
    monkeypatch.setenv("LIFE_INBOX_VAPID_PRIVATE_KEY", "private")
    sends = []
    monkeypatch.setattr(
        service, "list_notification_users",
        lambda: [{
            "user_id": 3,
            "daily_digest_time": "08:00",
            "timezone": "UTC",
            "include_unscheduled_prompt": False,
        }],
    )
    monkeypatch.setattr(
        service, "list_notification_tasks",
        lambda user_id: [task()],
    )
    monkeypatch.setattr(service, "list_push_subscriptions", lambda user_id: [])
    monkeypatch.setattr(
        service, "_send_push",
        lambda subscription, payload: sends.append(payload),
    )

    result = service.dispatch_due_notifications(
        datetime(2026, 10, 26, 7, 59, tzinfo=timezone.utc)
    )

    assert result == {"sent": 0, "skipped": 0, "failed": 0}
    assert sends == []
