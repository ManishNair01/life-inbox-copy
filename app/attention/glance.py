"""Your life at a glance: the Dashboard (change 011).

This week's captures and finished tasks, the busiest day, where your attention
went, what Captain noticed, growing and quiet topics, and what's coming up.
Worked out by code from your own data; no AI call. Pure functions, so tests
can feed in made-up rows and a fixed "today".
"""

from collections import Counter
from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Iterable, Optional

ATTENTION_DAYS = 30  # "where your attention went" looks back this far
GROWING_DAYS = 14  # a topic is growing with 2+ new notes in this window
QUIET_DAYS = 30  # a topic is quiet with no new note in this window
WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def local_date(timestamp: Optional[str], zone: tzinfo) -> Optional[date]:
    """The day a stored UTC timestamp falls on in the user's time zone."""
    if not timestamp:
        return None
    try:
        when = datetime.fromisoformat(str(timestamp))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(zone).date()


def _day(iso: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(str(iso)[:10]) if iso else None
    except ValueError:
        return None


def _short(day: date) -> str:
    return f"{WEEKDAY_NAMES[day.weekday()][:3]} {day.day} {MONTHS[day.month - 1]}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def build_glance(
    *,
    items: Iterable[dict],
    tasks: Iterable[dict],
    topics: Iterable[dict],
    bots: Iterable[dict],
    today: date,
    zone: tzinfo = timezone.utc,
    lens: Optional[str] = None,
) -> dict:
    """items: {"id", "created_at", "topic_id", "bot_key"} (the note's topic is
    your pick, else the AI's); tasks: task dicts (status, priority, due_on,
    completed_at, bot_key, ...); topics: topic dicts; bots: {"key", "name"}.
    With a lens, everything is limited to that life area."""
    bots = list(bots)
    live_topics = [topic for topic in topics if not topic.get("archived")]
    by_id = {topic["id"]: topic for topic in live_topics}

    def main_topic_id(topic_id: Optional[int]) -> Optional[int]:
        topic = by_id.get(topic_id)
        if topic is None:
            return None
        parent = topic.get("parent_topic_id")
        return parent if parent in by_id else topic["id"]

    in_scope = (lambda key: True) if lens is None else (lambda key: key == lens)
    notes = []
    for item in items:
        if not in_scope(item.get("bot_key")):
            continue
        created_on = local_date(item.get("created_at"), zone)
        if created_on is not None:
            notes.append({**item, "created_on": created_on, "main_topic": main_topic_id(item.get("topic_id"))})
    tasks = [task for task in tasks if in_scope(task.get("bot_key"))]
    open_tasks = [task for task in tasks if task.get("status") == "open"]

    # --- this week -----------------------------------------------------------------
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    this_week = [note for note in notes if week_start <= note["created_on"] <= week_end]
    done_this_week = [
        task for task in tasks
        if task.get("status") == "completed"
        and (done := local_date(task.get("completed_at"), zone)) is not None
        and week_start <= done <= week_end
    ]
    per_day = Counter(note["created_on"] for note in this_week)
    busiest = None
    if per_day:
        day, count = max(per_day.items(), key=lambda pair: (pair[1], pair[0]))
        busiest = {"date": day.isoformat(), "weekday": WEEKDAY_NAMES[day.weekday()], "count": count}

    # --- where your attention went (areas; with a lens, that area's topics) ----------
    window_start = today - timedelta(days=ATTENTION_DAYS - 1)
    recent = [note for note in notes if note["created_on"] >= window_start]
    if lens is None:
        per_area = Counter(note.get("bot_key") for note in recent)
        attention = [{"key": bot["key"], "name": bot["name"], "count": per_area.get(bot["key"], 0)} for bot in bots]
        if per_area.get(None):
            attention.append({"key": None, "name": "Not in an area yet", "count": per_area[None]})
    else:
        per_topic = Counter(note["main_topic"] for note in recent)
        mains = [topic for topic in live_topics
                 if topic.get("bot_key") == lens and main_topic_id(topic["id"]) == topic["id"]]
        attention = sorted(
            ({"id": topic["id"], "name": topic["name"], "count": per_topic.get(topic["id"], 0)} for topic in mains),
            key=lambda row: (-row["count"], row["name"]),
        )

    # --- growing and quiet topics (subtopics count toward their topic) ---------------
    growing_start = today - timedelta(days=GROWING_DAYS - 1)
    growing_counts = Counter(note["main_topic"] for note in notes
                             if note["main_topic"] is not None and note["created_on"] >= growing_start)
    growing = sorted(
        ({"id": topic_id, "name": by_id[topic_id]["name"], "count": count}
         for topic_id, count in growing_counts.items() if count >= 2),
        key=lambda row: (-row["count"], row["name"]),
    )[:3]
    last_seen: dict[int, date] = {}
    for note in notes:
        topic_id = note["main_topic"]
        if topic_id is not None and (topic_id not in last_seen or note["created_on"] > last_seen[topic_id]):
            last_seen[topic_id] = note["created_on"]
    quiet = sorted(
        ({"id": topic_id, "name": by_id[topic_id]["name"], "last_on": seen.isoformat(), "days": (today - seen).days}
         for topic_id, seen in last_seen.items() if (today - seen).days >= QUIET_DAYS),
        key=lambda row: (-row["days"], row["name"]),
    )[:3]

    # --- coming up ------------------------------------------------------------------
    awake = [task for task in open_tasks
             if not task.get("snoozed_until") or (_day(task["snoozed_until"]) or today) <= today]
    coming = sorted(
        (task for task in awake if (_day(task.get("due_on")) or date.min) >= today),
        key=lambda task: (task["due_on"], task.get("due_time") or "99:99", task["id"]),
    )[:5]
    coming_up = [{
        "id": task["id"], "text": task["text"], "due_on": task["due_on"], "due_time": task.get("due_time"),
        "priority": task["priority"], "bot_key": task.get("bot_key"),
        "timing_confirmed": bool(task.get("timing_confirmed")),
        "source_item_id": (task.get("source_item_ids") or [None])[0],
    } for task in coming]

    noticed = _noticed(
        lens=lens, bots=bots, attention=attention, recent_total=len(recent),
        open_tasks=awake, today=today, growing=growing, quiet=quiet,
    )
    return {
        "lens": lens,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "captured_this_week": len(this_week),
        "tasks_done_this_week": len(done_this_week),
        "open_tasks": len(open_tasks),
        "busiest_day": busiest,
        "attention_window_days": ATTENTION_DAYS,
        "attention": attention,
        "noticed": noticed,
        "growing": growing,
        "quiet": quiet,
        "coming_up": coming_up,
    }


def _noticed(*, lens, bots, attention, recent_total, open_tasks, today, growing, quiet) -> list[str]:
    """Up to 3 things Captain points out, most useful first."""
    lines = []
    overdue = sorted(
        (task for task in open_tasks if (_day(task.get("due_on")) or date.max) < today),
        key=lambda task: task["due_on"],
    )
    if overdue:
        first = overdue[0]
        lines.append(
            f"{_plural(len(overdue), 'task')} {'is' if len(overdue) == 1 else 'are'} overdue. "
            f"The oldest is “{first['text']}”, due {_short(_day(first['due_on']))}."
        )
    if recent_total >= 3 and attention:
        top = max(attention, key=lambda row: row["count"])
        if top["count"] >= 2:
            where = "your busiest area" if lens is None else "the busiest topic here"
            lines.append(f"{top['name']} is {where}: {top['count']} of {recent_total} notes in the last {ATTENTION_DAYS} days.")
    if lens is None and recent_total:
        silent = [row["name"] for row in attention if row["key"] is not None and row["count"] == 0]
        if silent and len(silent) < len(bots):
            verb = "has" if len(silent) == 1 else "have"
            lines.append(f"{_and(silent)} {verb} been quiet for {ATTENTION_DAYS} days.")
    if growing:
        lines.append(f"{growing[0]['name']} is growing: {growing[0]['count']} new notes in the last {GROWING_DAYS} days.")
    undated = [task for task in open_tasks if not task.get("due_on")]
    if undated:
        lines.append(f"{_plural(len(undated), 'open task')} {'has' if len(undated) == 1 else 'have'} no date yet.")
    if quiet:
        lines.append(f"Nothing new in {quiet[0]['name']} for {quiet[0]['days']} days.")
    if not lines:
        lines.append("A quiet stretch. What you add will show up here.")
    return lines[:3]
