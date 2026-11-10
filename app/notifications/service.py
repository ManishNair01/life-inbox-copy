"""Web Push delivery and scheduled task notification selection."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.attention.dates import normalize_time_of_day, parse_timing_phrase
from app.database import (
    claim_notification_delivery,
    delete_push_subscription_by_id,
    finish_notification_delivery,
    list_notification_tasks,
    list_notification_users,
    list_push_subscriptions,
)


logger = logging.getLogger(__name__)
ALLOWED_PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",
    "push.services.mozilla.com",
    "notify.windows.com",
    "push.apple.com",
)
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def vapid_public_key() -> Optional[str]:
    return os.getenv("LIFE_INBOX_VAPID_PUBLIC_KEY", "").strip() or None


def vapid_is_configured() -> bool:
    return bool(
        vapid_public_key()
        and os.getenv("LIFE_INBOX_VAPID_PRIVATE_KEY", "").strip()
    )


def validate_push_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not any(
            hostname == suffix or hostname.endswith("." + suffix)
            for suffix in ALLOWED_PUSH_HOST_SUFFIXES
        )
    ):
        raise ValueError("Unsupported browser push endpoint.")
    return parsed.geturl()


def _local_datetime(
    due_on: Optional[str],
    due_time: Optional[str],
    timezone_name: str,
) -> Optional[datetime]:
    if not due_on or not due_time or not _TIME_RE.fullmatch(due_time):
        return None
    try:
        due_date = date.fromisoformat(due_on)
        wall_time = time.fromisoformat(due_time)
        zone = ZoneInfo(timezone_name)
    except (ValueError, ZoneInfoNotFoundError):
        return None

    wall_datetime = datetime.combine(due_date, wall_time)
    localized = wall_datetime.replace(tzinfo=zone, fold=0)
    # Skip local times that do not exist during a daylight-saving transition.
    if localized.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != wall_datetime:
        return None
    return localized


def _eligible_high_priority(task: dict, timezone_name: str) -> Optional[datetime]:
    if (
        task["priority"] != "High"
        or not task["ai_generated"]
        or not task["due_on"]
    ):
        return None

    explicit_time = normalize_time_of_day(task.get("timing_text"))
    due_time = task.get("due_time") or explicit_time
    if not due_time or due_time != explicit_time:
        return None

    parsed = parse_timing_phrase(task.get("timing_text"))
    if parsed.needs_confirmation and not task["timing_confirmed"]:
        return None
    due_at = _local_datetime(task["due_on"], due_time, timezone_name)
    if due_at is None:
        return None
    return due_at


def _daily_payload(
    tasks: list[dict],
    *,
    local_date: date,
    unscheduled_count: int,
) -> Optional[dict]:
    due_today = [
        task
        for task in tasks
        if task.get("due_on") == local_date.isoformat()
        and not (
            task.get("snoozed_until")
            and task["snoozed_until"] > local_date.isoformat()
        )
    ]
    if not due_today and not unscheduled_count:
        return None

    due_today.sort(
        key=lambda task: (
            {"High": 0, "Medium": 1, "Low": 2}.get(task["priority"], 3),
            task["text"].casefold(),
        )
    )
    lines = [task["text"] for task in due_today]
    if unscheduled_count:
        lines.append(
            f"{unscheduled_count} unscheduled task(s) to review when you have time."
        )
    body = "\n".join(lines) if lines else "Review your unscheduled tasks when you have time."
    return {
        "title": f"Tasks for today · {len(due_today)} due",
        "body": body[:4000],
        "url": "/",
        "tag": f"life-inbox-daily-{local_date.isoformat()}",
    }


def _send_push(subscription: dict, payload: dict) -> None:
    from pywebpush import webpush

    private_key = os.getenv("LIFE_INBOX_VAPID_PRIVATE_KEY", "").strip()
    subject = (
        os.getenv("LIFE_INBOX_VAPID_SUBJECT", "").strip()
        or "mailto:admin@example.com"
    )
    webpush(
        subscription_info={
            "endpoint": subscription["endpoint"],
            "keys": {
                "p256dh": subscription["p256dh"],
                "auth": subscription["auth"],
            },
        },
        data=json.dumps(payload, ensure_ascii=False),
        vapid_private_key=private_key,
        vapid_claims={"sub": subject},
        ttl=3600,
    )


def _deliver(
    *,
    user_id: int,
    task_id: Optional[int],
    kind: str,
    local_date: date,
    idempotency_key: str,
    payload: dict,
    now: datetime,
) -> Optional[bool]:
    subscriptions = list_push_subscriptions(user_id)
    if not subscriptions:
        return None
    if not claim_notification_delivery(
        user_id=user_id,
        task_id=task_id,
        kind=kind,
        local_date=local_date.isoformat(),
        idempotency_key=idempotency_key,
        now=now,
    ):
        return None

    try:
        if not vapid_is_configured():
            raise RuntimeError(
                "Web Push is not configured; set the VAPID public and private keys."
            )

        delivered = False
        failures = []
        for subscription in subscriptions:
            try:
                _send_push(subscription, payload)
                delivered = True
            except Exception as exc:
                status_code = getattr(
                    getattr(exc, "response", None), "status_code", None
                )
                if status_code in {404, 410}:
                    delete_push_subscription_by_id(subscription["id"])
                failures.append(
                    "Push endpoint failed"
                    + (f" (HTTP {status_code})" if status_code else "")
                )
                logger.warning(
                    "Push delivery failed for user %s (%s)",
                    user_id,
                    f"HTTP {status_code}" if status_code else type(exc).__name__,
                )

        error = (
            None
            if delivered
            else "; ".join(failures) or "No push endpoints available."
        )
        finish_notification_delivery(
            idempotency_key,
            delivered=delivered,
            now=now,
            error=error,
        )
        return delivered
    except Exception as exc:
        finish_notification_delivery(
            idempotency_key,
            delivered=False,
            now=now,
            error=f"Delivery error: {type(exc).__name__}",
        )
        raise


def _scout_push(user: dict, tasks: list[dict], local_now: datetime, now: datetime, result: dict) -> None:
    """Scout's weekly catch-up (change 018), once per catch-up slot."""
    from app import scout

    user_id = user["user_id"]
    try:
        payload = scout.push_for(user, tasks, local_now)
        if payload is None:
            return
        slot = payload.pop("slot")
        delivery = _deliver(
            user_id=user_id,
            task_id=None,
            kind="scout_catchup",
            local_date=date.fromisoformat(slot),
            idempotency_key=f"scout:{user_id}:{slot}",
            payload=payload,
            now=now,
        )
    except Exception:
        logger.exception("Scout catch-up notification failed for user %s", user_id)
        result["failed"] += 1
        return
    if delivery is True:
        result["sent"] += 1
    elif delivery is False:
        result["failed"] += 1


def dispatch_due_notifications(now: Optional[datetime] = None) -> dict:
    """Send due digests and one-hour High-task alerts for enabled users."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Dispatch time must be timezone-aware.")
    current = current.astimezone(timezone.utc)

    result = {"sent": 0, "skipped": 0, "failed": 0}
    for user in list_notification_users():
        user_id = user["user_id"]
        try:
            zone = ZoneInfo(user["timezone"])
        except ZoneInfoNotFoundError:
            logger.error("Invalid notification timezone for user %s", user_id)
            result["failed"] += 1
            continue

        local_now = current.astimezone(zone)
        tasks = list_notification_tasks(user_id)
        unscheduled_count = sum(
            1 for task in tasks if not task.get("due_on") and not task.get("someday")
        )
        _scout_push(user, tasks, local_now, current, result)
        if (
            _TIME_RE.fullmatch(user["daily_digest_time"])
            and local_now.strftime("%H:%M") >= user["daily_digest_time"]
        ):
            payload = _daily_payload(
                tasks,
                local_date=local_now.date(),
                unscheduled_count=(
                    unscheduled_count
                    if user["include_unscheduled_prompt"]
                    else 0
                ),
            )
            if payload is not None:
                key = f"daily:{user_id}:{local_now.date().isoformat()}"
                try:
                    delivery = _deliver(
                        user_id=user_id,
                        task_id=None,
                        kind="daily_digest",
                        local_date=local_now.date(),
                        idempotency_key=key,
                        payload=payload,
                        now=current,
                    )
                    if delivery is True:
                        result["sent"] += 1
                    elif delivery is False:
                        result["failed"] += 1
                    else:
                        result["skipped"] += 1
                except Exception as exc:
                    logger.exception(
                        "Daily notification failed for user %s", user_id
                    )
                    result["failed"] += 1

        for task in tasks:
            due_at = _eligible_high_priority(task, user["timezone"])
            if due_at is None:
                continue
            reminder_at = due_at - timedelta(hours=1)
            age = current - reminder_at.astimezone(timezone.utc)
            if age < timedelta(0) or age >= timedelta(minutes=5):
                continue
            if (
                task.get("snoozed_until")
                and task["snoozed_until"] > local_now.date().isoformat()
            ):
                continue
            key = (
                f"high:{user_id}:{task['id']}:"
                f"{task['due_on']}:{task['due_time'] or normalize_time_of_day(task.get('timing_text'))}"
            )
            payload = {
                "title": "High-priority task in one hour",
                "body": task["text"][:1000],
                "url": "/",
                "task_id": task["id"],
                "tag": f"life-inbox-task-{task['id']}",
            }
            try:
                delivery = _deliver(
                    user_id=user_id,
                    task_id=task["id"],
                    kind="high_priority_reminder",
                    local_date=due_at.date(),
                    idempotency_key=key,
                    payload=payload,
                    now=current,
                )
                if delivery is True:
                    result["sent"] += 1
                elif delivery is False:
                    result["failed"] += 1
                else:
                    result["skipped"] += 1
            except Exception as exc:
                logger.exception(
                    "High-priority notification failed for user %s task %s",
                    user_id,
                    task["id"],
                )
                result["failed"] += 1

    return result
