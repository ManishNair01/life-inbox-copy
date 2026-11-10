"""Scout, the catch-up helper (change 018). Worked out by code: no AI call.

When Scout asks (decision L: the weekly catch-up is Sunday 19:00, local time,
and you can change it in Settings):

- the day after a task's date: "Did you do it?" (Done / New date / Drop it);
- in the weekly catch-up, at most 10 questions: past-date tasks first, then
  undated tasks waiting 14+ days, then Someday tasks untouched for 30+ days
  (asked once a month);
- after a break: "You've been away 9 days. A 1-minute catch-up?" (7+ days).

Each answer is a task event (by Scout) and a short-term memory fact: "Captain
updated the Learning & work bot's memory: Python quiz: done". Dropping a task
offers an optional reason (decision M). Against overwhelm: kind wording, a
few questions at a time, and two bulk actions (old tasks to Someday, past
tasks to next week), each asked before it runs.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from app import bots, database

MAX_QUESTIONS = 10
AWAY_DAYS = 7
UNDATED_DAYS = 14
SOMEDAY_DAYS = 30
OLD_DAYS = 30
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
ACTIONS = ("done", "reschedule", "drop", "someday", "keep", "skip")
DROP_REASONS = ("Not needed any more", "Someone else did it", "Too much right now")


def _day(iso: Optional[str]) -> str:
    try:
        value = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return str(iso or "")
    return f"{value.strftime('%a')} {value.day} {value.strftime('%b')}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _clip(text: Optional[str], limit: int = 80) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _local_now(now: Optional[datetime] = None) -> datetime:
    from app.attention.dates import configured_timezone

    zone = configured_timezone()
    current = now or datetime.now(zone)
    return current.astimezone(zone) if current.tzinfo else current.replace(tzinfo=zone)


def _parse(stamp: Optional[str]) -> Optional[datetime]:
    if not stamp:
        return None
    try:
        value = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=_local_now().tzinfo)


def catchup_slot(settings: dict, now: datetime) -> datetime:
    """The most recent weekly catch-up time at or before `now` (local)."""
    weekday = WEEKDAYS.index(settings.get("catchup_day") or "sun")
    hours, minutes = (int(part) for part in (settings.get("catchup_time") or "19:00").split(":"))
    slot = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    slot -= timedelta(days=(slot.weekday() - weekday) % 7)
    if slot > now:
        slot -= timedelta(days=7)
    return slot


def weekly_due(settings: dict, now: datetime) -> bool:
    slot = catchup_slot(settings, now)
    joined = _parse(settings.get("created_at"))
    if joined is not None and joined > slot:
        return False  # a new account waits for its first catch-up
    done = _parse(settings.get("last_catchup_at"))
    return done is None or done < slot


def _question(kind, key, rank, task, text, actions, **data):
    return {"id": key, "kind": kind, "rank": rank, "task_id": task["id"], "title": _clip(task["text"]),
            "text": text, "actions": actions, "item_id": (task.get("source_item_ids") or [None])[0],
            "bot_key": task.get("bot_key"), "data": data}


def _act(action: str, label: str, primary: bool = False) -> dict:
    return {"action": action, "label": label, "primary": primary}


def build_questions(facts: dict, now: datetime, *, session: bool) -> list[dict]:
    """Scout's questions, ranked. Outside a catch-up session only the
    day-after questions; in one, the undated and Someday ones too."""
    today = now.date()
    month = today.strftime("%Y-%m")
    questions = []
    for task in facts["tasks"]:
        if task["someday"]:
            if not session:
                continue
            touched = _parse(task.get("someday_since") or task.get("updated_at"))
            if touched is not None and (now - touched).days >= SOMEDAY_DAYS:
                questions.append(_question(
                    "someday", f"someday:{task['id']}:{month}", 300, task,
                    "On your Someday list for a while. Still someday?",
                    [_act("keep", "Keep it", primary=True), _act("reschedule", "Plan it"), _act("drop", "Drop it")]))
            continue
        due = task.get("due_on")
        if due and due < today.isoformat():
            questions.append(_question(
                # Yesterday's first (what you remember best), older ones after.
                "past", f"past:{task['id']}:{due}", 100 + min(99, (today - date.fromisoformat(due)).days), task,
                f"It was on {_day(due)}. Did you do it?",
                [_act("done", "Done", primary=True), _act("reschedule", "Not yet, new date"), _act("drop", "Drop it")],
                due_on=due))
        elif session and not due and not task.get("suggested_due_on"):
            created = _parse(task.get("created_at"))
            if created is not None and (now - created).days >= UNDATED_DAYS:
                questions.append(_question(
                    "undated", f"undated:{task['id']}", 200, task,
                    f"Waiting {_plural((now - created).days, 'day')} without a date. Still want to do it?",
                    [_act("reschedule", "Give it a date", primary=True), _act("someday", "Someday"),
                     _act("drop", "Drop it")]))
    answered = facts.get("answered") or set()
    questions = [question for question in questions if question["id"] not in answered]
    questions.sort(key=lambda question: (question["rank"], question["id"]))
    return questions


def state(user_id: Optional[int] = None, now: Optional[datetime] = None, *, mark_seen: bool = False) -> dict:
    """What Scout has for you now: why it's asking, and its questions."""
    current = _local_now(now)
    facts = database.scout_facts(user_id)
    settings = facts["settings"]
    away = settings.get("away_days")
    if mark_seen:
        seen = _parse(settings.get("last_seen_at"))
        if seen is not None and (current - seen).days >= AWAY_DAYS:
            away = (current - seen).days
        database.update_settings(user_id, last_seen_at=current.isoformat(), away_days=away)
    weekly = weekly_due(settings, current)
    mode = "away" if away else ("weekly" if weekly else "daily")
    questions = build_questions(facts, current, session=mode != "daily")
    shown = questions[:MAX_QUESTIONS]
    count = len(shown)
    if not count:
        intro = "All caught up. Nothing to check."
    elif mode == "away":
        intro = f"You've been away {away} days. A 1-minute catch-up? {_plural(count, 'quick question')}."
    elif mode == "weekly":
        intro = f"Let's tidy up: {_plural(count, 'quick question')}."
    else:
        intro = f"{_plural(count, 'quick question')} about things that were due."
    return {
        "mode": mode, "intro": intro, "questions": shown, "total": len(questions),
        "away_days": away, "catchup_due": weekly or bool(away),
        "next_catchup": (catchup_slot(settings, current) + timedelta(days=7)).isoformat(),
        "drop_reasons": list(DROP_REASONS), "bulk": bulk_plan(facts, current),
    }


def bulk_plan(facts: dict, now: datetime) -> dict:
    """What the two bulk actions would move (nothing moves until you say)."""
    today = now.date().isoformat()
    old, past = [], []
    for task in facts["tasks"]:
        if task["someday"]:
            continue
        created = _parse(task.get("created_at"))
        if task.get("due_on") and task["due_on"] < today:
            past.append(task["id"])
        if created is not None and (now - created).days >= OLD_DAYS and (
                not task.get("due_on") or task["due_on"] < (now.date() - timedelta(days=OLD_DAYS)).isoformat()):
            old.append(task["id"])
    return {"old_to_someday": old, "past_to_next_week": past}


def next_week(now: datetime) -> str:
    """Next Monday (local): where "Snooze these to next week" puts past tasks."""
    today = now.date()
    return (today + timedelta(days=7 - today.weekday())).isoformat()


def _memory_line(task: dict, words: str) -> str:
    bot = bots.BOTS_BY_KEY.get(task.get("bot_key") or "")
    fact = database.remember(f"“{_clip(task['text'], 80)}”: {words}.", kind="short_term", source_kind="scout",
                             bot_key=task.get("bot_key"), item_ids=[i for i in task.get("source_item_ids") or [] if i][:1],
                             status="confirmed",
                             valid_until=(_local_now().date() + timedelta(days=7)).isoformat())
    if fact is None:
        return f"{_clip(task['text'], 60)}: {words}."
    if bot is None:
        return f"Captain noted it: {_clip(task['text'], 60)}: {words}."
    return f"Captain updated the {bot.name} bot's memory: {_clip(task['text'], 60)}: {words}."


class QuestionGone(LookupError):
    """The question was already answered, or its situation changed."""


def answer(question_id: str, action: str, *, due_on: Optional[str] = None, due_time: Optional[str] = None,
           reason: Optional[str] = None, now: Optional[datetime] = None) -> dict:
    """Carry out your answer; returns what was done and Scout's new state."""
    if action not in ACTIONS:
        raise ValueError("That isn't one of Scout's answers.")
    current = _local_now(now)
    facts = database.scout_facts()
    questions = {q["id"]: q for q in build_questions(facts, current, session=True)}
    question = questions.get(question_id)
    if question is None:
        raise QuestionGone("This question was already answered.")
    if action != "skip" and action not in {item["action"] for item in question["actions"]}:
        raise ValueError("That isn't one of this question's answers.")
    task = next(task for task in facts["tasks"] if task["id"] == question["task_id"])
    reason = (str(reason).strip()[:200] or None) if reason else None
    said = "Skipped. Scout won't ask about it again."
    if action == "done":
        database.set_task_status(task["id"], database.TASK_COMPLETED, by="scout")
        said = _memory_line(task, "done")
    elif action == "reschedule":
        if not due_on:
            raise ValueError("Pick the new date.")
        try:
            date.fromisoformat(due_on)
        except ValueError as exc:
            raise ValueError("That isn't a real date.") from exc
        database.set_task_date(task["id"], due_on, due_time, by="scout")
        said = _memory_line(task, f"moved to {_day(due_on)}")
    elif action == "drop":
        database.set_task_status(task["id"], database.TASK_DISMISSED, by="scout", reason=reason)
        said = _memory_line(task, "dropped" + (f" ({reason.lower()})" if reason else ""))
    elif action == "someday":
        database.set_task_someday([task["id"]], True, by="scout")
        said = f"Moved to Someday: {_clip(task['text'], 60)}. It stays off your dates and lists."
    elif action == "keep":
        database.record_task_event(task["id"], "kept", by="scout")
        database.set_task_someday([task["id"]], True, by=None)  # touched: asked again in a month
        said = "Kept on your Someday list."
    database.record_captain_answer(question_id, "scout", action, {"question": question["text"], "title": question["title"],
                                                                    "reason": reason}, task_id=task["id"])
    return {"said": said, "scout": state(now=now)}


def finish(now: Optional[datetime] = None) -> dict:
    """You finished (or closed) the catch-up: the next one is next week."""
    current = _local_now(now)
    database.update_settings(last_catchup_at=current.isoformat(), away_days=None)
    return state(now=now)


def run_bulk(which: str, now: Optional[datetime] = None) -> dict:
    current = _local_now(now)
    plan = bulk_plan(database.scout_facts(), current)
    if which == "old_to_someday":
        ids = plan["old_to_someday"]
        database.set_task_someday(ids, True, by="scout")
        said = f"Moved {_plural(len(ids), 'task')} to Someday."
    elif which == "past_to_next_week":
        ids = plan["past_to_next_week"]
        day = next_week(current)
        facts = {task["id"]: task for task in database.scout_facts()["tasks"]}
        for task_id in ids:
            database.set_task_date(task_id, day, facts[task_id].get("due_time"), by="scout")
        said = f"Moved {_plural(len(ids), 'task')} to {_day(day)}."
    else:
        raise ValueError("Unknown bulk action.")
    return {"said": said, "moved": ids, "scout": state(now=now)}


def push_for(user: dict, tasks: list[dict], now: datetime) -> Optional[dict]:
    """The weekly catch-up push, for the existing dispatcher. Worked out only
    from the user's notification row (which carries the catch-up settings) and
    the open tasks the dispatcher already read: no database access here."""
    if "catchup_day" not in user:
        return None
    settings = {key: user.get(key) for key in ("catchup_day", "catchup_time", "last_catchup_at", "created_at")}
    if not (weekly_due(settings, now) or user.get("away_days")):
        return None
    today = now.date().isoformat()
    past = [task for task in tasks if task.get("due_on") and task["due_on"] < today and not task.get("someday")]
    if not past:
        return None
    slot = catchup_slot(settings, now).date().isoformat()
    return {
        "title": "Scout · your weekly catch-up",
        "body": f"{_plural(len(past), 'task')} whose day has passed. A 1-minute catch-up?",
        "url": "/#/scout",
        "tag": f"life-inbox-scout-{slot}",
        "slot": slot,
    }
