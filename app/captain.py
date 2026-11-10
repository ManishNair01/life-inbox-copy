"""Captain's "Needs you" list (change 013).

One place for everything that needs a quick answer from you, worked out by code
from your own data: no AI call. Kinds of card, each with one-tap answers:

- ``date``: a guessed date waiting for your OK (Check it / Not now)
- ``moved``: a date your edit moved, waiting for your OK (Check it / Not now)
- ``no_date``: a time-bound task with no date (Set date / Drop it / Not now)
- ``failed``: a capture that couldn't be read (Retry / Add a note / Delete / Not now)
- ``area``: a note with no real topic, only the old catch-all (its two likeliest
  topics / Other topic / Not now). Rule R6: don't guess, ask.
- ``unfiled``: a note Life Inbox hasn't filed yet (File it / Not now)
- ``review``: a note you marked for review (Open / Done)
- ``topic_area``: a topic with no life area (the five areas / Not now)
- ``clash``: two dated tasks within an hour of each other (Check / Ignore)
- ``idea``: a maybe in your words (Add task / Not now; change 014a)
- ``plan``: a note that seems to move a plan you have (Yes, move it / No, it's
  a different one; change 017)
- ``proposal``: a topic the weekly review suggests (Create it / Rename / Not
  now / Don't suggest this; change 020). Never made without you.
- ``fact``: a fact the weekly review thinks is true about you (Yes / No /
  Edit; change 020)

Rules: cards are ranked by how soon they matter; at most one card per note
(P6), the next one shows once you answer; an answered card, "Not now"
included, doesn't come back unless its situation changes (a new key); each
user only ever sees their own (the facts are read for the signed-in user).
"""

import re
from datetime import date
from typing import Optional

from app import bots, database
from app.organizer import CATCH_ALL_TOPIC, topic_choices

# Tasks that are usually tied to a day; a dated one is fine, an undated one asks.
TIME_BOUND = re.compile(
    r"\b(meet(ing)?|appointment|appt|exam|quiz|test|deadline|due|submit|submission|interview|"
    r"pay|renew|book|attend|event|class|lecture|flight|train|party|dinner|lunch|visit|"
    r"deliver|return|apply|register|rsvp|talk to|call|follow up)\b",
    re.I,
)
CLASH_MINUTES = 60
CLASH_DAYS = 30
MAX_CARDS = 20

KIND_HEADINGS = {
    "date": "A date to check",
    "moved": "Your edit moved a date",
    "no_date": "No date yet",
    "failed": "Couldn't read this",
    "area": "Which topic?",
    "unfiled": "Not filed yet",
    "review": "You marked this for review",
    "topic_area": "Which life area?",
    "clash": "Two things at once",
    "idea": "Make this a task?",
    "plan": "Did a plan move?",
    "proposal": "A new topic?",
    "fact": "Is this right?",
}

# Answers the server carries out (POST /api/captain/needs-you/{id}/resolve).
# The others (Check it, Set date, Retry, File it, Open, Other topic, Check) use
# the app's existing actions, after which the card simply goes away.
SERVER_ACTIONS = {"not_now", "ignore", "drop", "add_note", "delete", "pick", "done", "add", "move", "different",
                  "create", "never", "yes", "no"}


def _day(iso: Optional[str]) -> str:
    try:
        value = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return str(iso or "")
    return f"{value.strftime('%a')} {value.day} {value.strftime('%b')}"


def _clip(text: Optional[str], limit: int = 80) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _days_until(iso: Optional[str], today: date) -> int:
    try:
        return max(0, (date.fromisoformat(str(iso)[:10]) - today).days)
    except (TypeError, ValueError):
        return 60


def _minutes(clock: Optional[str]) -> Optional[int]:
    if not clock or not re.fullmatch(r"\d{2}:\d{2}", clock):
        return None
    hours, minutes = clock.split(":")
    return int(hours) * 60 + int(minutes)


def _card(kind, key, rank, title, text, actions, item_id=None, task_id=None, topic_id=None, data=None):
    return {
        "id": key,
        "kind": kind,
        "heading": KIND_HEADINGS[kind],
        "title": title,
        "text": text,
        "item_id": item_id,
        "task_id": task_id,
        "topic_id": topic_id,
        "actions": actions,
        "data": data or {},
        "rank": rank,
    }


def _act(action: str, label: str, value=None, primary: bool = False) -> dict:
    return {"action": action, "label": label, "value": value, "primary": primary}


def _words(task: dict) -> Optional[str]:
    words = (task.get("timing_text") or "").strip()
    if not words or words.lower() == (task.get("text") or "").strip().lower():
        return None
    return _clip(words, 60)


def _task_cards(facts: dict, today: date) -> list[dict]:
    cards = []
    moved = facts.get("moved") or {}
    for task in facts["tasks"]:
        if task.get("someday"):
            continue  # a Someday task has no date on purpose (change 018)
        item_id = (task.get("source_item_ids") or [None])[0]
        title = _clip(task["text"])
        change = moved.get(task["id"])
        if change:
            to = change["to_due_on"]
            when = f"{_day(to)} at {change['to_due_time']}" if change.get("to_due_time") else _day(to)
            frm = _day(change["from_due_on"]) if change.get("from_due_on") else None
            text = f"Your edit moved it{f' from {frm}' if frm else ''} to {when}. Is that right?"
            cards.append(_card(
                "moved", f"moved:{task['id']}:{to}", 100 + _days_until(to, today), title, text,
                [_act("check", "Check it", primary=True), _act("not_now", "Not now")],
                item_id=item_id, task_id=task["id"],
                data={"to": to, "from": change.get("from_due_on"), "from_time": change.get("from_due_time"), "when": when},
            ))
            continue
        if task.get("due_confidence") == database.DATE_SUGGESTED and task.get("suggested_due_on"):
            day = task["suggested_due_on"]
            words = _words(task)
            text = f"You wrote “{words}”: is it {_day(day)}?" if words else f"Is it {_day(day)}?"
            cards.append(_card(
                "date", f"date:{task['id']}:{day}", 100 + _days_until(day, today), title, text,
                [_act("check", "Check it", primary=True), _act("not_now", "Not now")],
                item_id=item_id, task_id=task["id"], data={"day": day, "time": task.get("suggested_due_time")},
            ))
            continue
        snoozed = task.get("snoozed_until") and task["snoozed_until"] > today.isoformat()
        if (not task.get("due_on") and not task.get("suggested_due_on") and item_id is not None
                and not snoozed and TIME_BOUND.search(task["text"] or "")):
            cards.append(_card(
                "no_date", f"nodate:{task['id']}", 400, title, "It sounds like it has a day. When is it?",
                [_act("set_date", "Set date", primary=True), _act("drop", "Drop it"), _act("not_now", "Not now")],
                item_id=item_id, task_id=task["id"],
            ))
    return cards


def _clash_cards(facts: dict, today: date) -> list[dict]:
    timed = [
        task for task in facts["tasks"]
        if task.get("due_on") and _minutes(task.get("due_time")) is not None
        and 0 <= (date.fromisoformat(task["due_on"]) - today).days <= CLASH_DAYS
    ]
    timed.sort(key=lambda task: (task["due_on"], task["due_time"], task["id"]))
    cards, used = [], set()
    for index, first in enumerate(timed):
        for second in timed[index + 1:]:
            if second["due_on"] != first["due_on"]:
                break
            if abs(_minutes(second["due_time"]) - _minutes(first["due_time"])) >= CLASH_MINUTES:
                continue
            if set(first.get("source_item_ids") or []) & set(second.get("source_item_ids") or []):
                continue  # one note's own tasks: the same plan, not a clash
            if first["id"] in used or second["id"] in used:
                continue
            used.update((first["id"], second["id"]))
            day = first["due_on"]
            cards.append(_card(
                "clash", f"clash:{first['id']}:{second['id']}:{day}:{first['due_time']}",
                110 + _days_until(day, today), f"{_day(day)} at {first['due_time']}",
                f"“{_clip(first['text'], 50)}” and “{_clip(second['text'], 50)}” are at about the same time.",
                [_act("check", "Check", primary=True), _act("ignore", "Ignore")],
                task_id=first["id"],
                data={"day": day, "task_ids": [first["id"], second["id"]],
                      "item_ids": [(first.get("source_item_ids") or [None])[0], (second.get("source_item_ids") or [None])[0]]},
            ))
    return cards


def _note_cards(facts: dict) -> list[dict]:
    topics = [topic for topic in facts["topics"] if not topic.get("archived")]
    cards = []
    for position, note in enumerate(facts["notes"]):
        title = _clip(note["title"])
        if note["processing_status"] == "failed":
            where = note.get("source_url") or note.get("original_filename")
            reason = _clip(note.get("error_message") or "Reading it failed.", 120)
            cards.append(_card(
                "failed", f"failed:{note['id']}", 200, title if title != where else _clip(where),
                reason,
                [_act("retry", "Retry", primary=True), _act("add_note", "Add a note"),
                 _act("delete", "Delete"), _act("not_now", "Not now")],
                item_id=note["id"], data={"item_type": note["item_type"], "where": where},
            ))
            continue
        if note["processing_status"] != "ready":
            continue
        if not note["filed"]:
            cards.append(_card(
                "unfiled", f"unfiled:{note['id']}", 300 + position, title,
                "Life Inbox hasn't filed this note yet.",
                [_act("file", "File it", primary=True), _act("not_now", "Not now")],
                item_id=note["id"],
            ))
            continue
        if note.get("pending"):
            by_id = {topic["id"]: topic for topic in topics}
            choices = [by_id[choice] for choice in note.get("choices") or [] if choice in by_id][:2]
            if not choices:
                choices = topic_choices(note["text"] or note["title"], topics, limit=2)
            actions = [_act("pick", choice["name"], value=choice["id"], primary=index == 0) for index, choice in enumerate(choices)]
            actions += [_act("other", "Other topic…"), _act("not_now", "Not now")]
            cards.append(_card(
                "area", f"area:{note['id']}:pending", 300 + position, title,
                "Life Inbox wasn't sure where this goes. Which topic fits?",
                actions, item_id=note["id"], data={"choices": [choice["id"] for choice in choices]},
            ))
            continue
        if note["topic_id"] is None or (note.get("topic_name") or "").lower() == CATCH_ALL_TOPIC.lower():
            choices = topic_choices(note["text"] or note["title"], topics, limit=2)
            where = "the old catch-all, Personal / Reference" if note["topic_id"] else "no topic"
            actions = [_act("pick", choice["name"], value=choice["id"], primary=index == 0) for index, choice in enumerate(choices)]
            actions += [_act("other", "Other topic…"), _act("not_now", "Not now")]
            cards.append(_card(
                "area", f"area:{note['id']}:{note['topic_id'] or 'none'}", 300 + position, title,
                f"It's in {where}. Which topic fits?" if choices else f"It's in {where}. Pick the topic that fits.",
                actions, item_id=note["id"], data={"choices": [choice["id"] for choice in choices]},
            ))
            continue
        if note["needs_review"]:
            cards.append(_card(
                "review", f"review:{note['id']}", 450 + position, title, "Have another look when you can.",
                [_act("open", "Open", primary=True), _act("done", "Done")],
                item_id=note["id"],
            ))
    return cards


def _topic_cards(facts: dict) -> list[dict]:
    cards = []
    for topic in facts["topics"]:
        if topic.get("archived") or topic.get("bot_key") or topic.get("parent_topic_id"):
            continue
        if (topic.get("name") or "").lower() == CATCH_ALL_TOPIC.lower():
            continue
        guess = bots.bot_for_text(f"{topic['name']} {topic.get('description') or ''}")
        order = sorted(bots.BOT_KEYS, key=lambda key: key != guess)
        cards.append(_card(
            "topic_area", f"topicarea:{topic['id']}", 500, topic["name"],
            "Every topic belongs to one life area. It helps Life Inbox file your notes.",
            [_act("pick", bots.BOTS_BY_KEY[key].name, value=key, primary=key == guess) for key in order]
            + [_act("not_now", "Not now")],
            topic_id=topic["id"], data={"suggested": guess},
        ))
    return cards


def _idea_cards(facts: dict) -> list[dict]:
    """A maybe in your words ("I should probably call Rahul"): ask before it
    becomes a task (change 014a). Someday ideas never ask."""
    cards = []
    for idea in facts.get("ideas") or []:
        if idea["intent"] != "tentative":
            continue
        when = f" ({_clip(idea['timing_text'], 40)})" if idea.get("timing_text") else ""
        cards.append(_card(
            "idea", f"idea:{idea['id']}", 350, _clip(idea["text"]),
            f"You wrote it as a maybe{when}. Add it as a task?",
            [_act("add", "Add task", primary=True), _act("not_now", "Not now")],
            item_id=idea["item_id"], data={"idea_id": idea["id"]},
        ))
    return cards


def _when(day: Optional[str], clock: Optional[str]) -> str:
    return f"{_day(day)}{f' at {clock}' if clock else ''}" if day else "no day yet"


def _plan_cards(facts: dict) -> list[dict]:
    """A note that seems to move a plan (017): nothing changes until you say."""
    cards = []
    for update in facts.get("plan_updates") or []:
        cards.append(_card(
            "plan", f"plan:{update['id']}", 150, _clip(update["task_text"]),
            f"Your note seems to move it from {_when(update['from_due_on'], update['from_due_time'])} "
            f"to {_when(update['new_due_on'], update['new_due_time'])}. Move it?",
            [_act("move", "Yes, move it", primary=True), _act("different", "No, it's a different one")],
            item_id=update["item_id"], task_id=update["task_id"],
            data={"plan_update_id": update["id"], "to": update["new_due_on"], "to_time": update["new_due_time"]},
        ))
    return cards


def _review_cards(facts: dict) -> list[dict]:
    """The weekly review's questions (change 020): topics and facts, asked first."""
    cards = []
    for proposal in facts.get("proposals") or []:
        area = bots.BOTS_BY_KEY.get(proposal["bot_key"])
        examples = ", ".join(f"“{_clip(title, 40)}”" for title in proposal["titles"][:3])
        where = f"under {proposal['parent_name']}" if proposal.get("parent_name") else ""
        cards.append(_card(
            "proposal", f"proposal:{proposal['id']}", 450, proposal["name"],
            f"Your {area.name if area else ''} notes keep coming back to this. A topic {where} for "
            f"{len(proposal['item_ids'])} notes, like {examples}?",
            [_act("create", "Create it", primary=True), _act("rename", "Rename"), _act("not_now", "Not now"),
             _act("never", "Don't suggest this")],
            data={"proposal_id": proposal["id"], "item_ids": proposal["item_ids"], "bot_key": proposal["bot_key"]},
        ))
    for fact in facts.get("fact_checks") or []:
        cards.append(_card(
            "fact", f"fact:{fact['id']}", 460, fact["text"],
            "From your weekly review: Life Inbox thinks this is true about you. Is it?",
            [_act("yes", "Yes", primary=True), _act("no", "No"), _act("edit", "Edit")],
            data={"fact_id": fact["id"]},
        ))
    return cards


def build_cards(facts: dict) -> list[dict]:
    """Every open card for these facts, ranked, at most one per note (P6)."""
    today = date.fromisoformat(facts["today"])
    cards = (_task_cards(facts, today) + _clash_cards(facts, today) + _note_cards(facts)
             + _idea_cards(facts) + _plan_cards(facts) + _review_cards(facts) + _topic_cards(facts))
    answered = facts.get("answered") or set()
    cards = [card for card in cards if card["id"] not in answered]
    cards.sort(key=lambda card: (card["rank"], card["id"]))
    seen_notes, kept = set(), []
    for card in cards:
        # A clash is a question about both of its notes.
        notes = {note for note in card["data"].get("item_ids", [])} if card["kind"] == "clash" else {card["item_id"]}
        notes.discard(None)
        if notes & seen_notes:
            continue
        seen_notes.update(notes)
        kept.append(card)
    return kept


def needs_you() -> dict:
    """The signed-in user's list: the top cards and how many there are in all."""
    cards = build_cards(database.captain_facts())
    return {"cards": cards[:MAX_CARDS], "total": len(cards)}


class CardGone(LookupError):
    """The card was already answered, or its situation changed."""


def resolve(card_id: str, action: str, value=None) -> dict:
    """Carry out your answer to a card and remember it; returns the new list."""
    if action not in SERVER_ACTIONS:
        raise ValueError("That answer is made in the app, not here.")
    cards = {card["id"]: card for card in build_cards(database.captain_facts())}
    card = cards.get(card_id)
    if card is None:
        raise CardGone("This question was already answered.")
    allowed = {item["action"]: item for item in card["actions"]}
    if action not in allowed:
        raise ValueError("That isn't one of this question's answers.")
    detail = {"heading": card["heading"], "title": card["title"], "question": card["text"]}

    if action == "pick" and card["kind"] == "area":
        choices = card["data"].get("choices") or []
        if value not in choices:
            raise ValueError("Pick one of the topics on the card.")
        database.update_item_insight_overrides(card["item_id"], user_topic_id=int(value))
        detail["picked"] = next(item["label"] for item in card["actions"] if item["value"] == value)
        detail["choices"] = [item["label"] for item in card["actions"] if item["action"] == "pick"]
    elif action == "pick" and card["kind"] == "topic_area":
        if value not in bots.BOTS_BY_KEY:
            raise ValueError("Pick one of the five life areas.")
        database.update_topic_in_db(card["topic_id"], bot_key=value)
        detail["picked"] = bots.BOTS_BY_KEY[value].name
        database.remember(f"Your topic “{card['title']}” belongs to {detail['picked']}.", kind="example",
                          source_kind="needs_you", bot_key=value, status="confirmed")
        detail["suggested"] = card["data"].get("suggested")
    elif action == "drop":
        database.set_task_status(card["task_id"], database.TASK_DISMISSED)
    elif action == "add_note":
        note = str(value or "").strip()
        if not note:
            raise ValueError("Write a few words about what this was.")
        if len(note) > 2000:
            raise ValueError("Keep your note under 2000 characters.")
        database.add_note_to_failed_capture(card["item_id"], note)
        detail["note"] = note
    elif action == "delete":
        database.delete_item_from_db(card["item_id"])
    elif action == "done":
        database.update_item_insight_overrides(card["item_id"], needs_review=False)
    elif action == "add":
        task = database.add_idea_as_task(card["data"]["idea_id"])
        detail["task_id"] = task and task["id"]
    elif action == "not_now" and card["kind"] == "idea":
        database.dismiss_idea(card["data"]["idea_id"])
    elif action == "create":
        name = str(value).strip() if value not in (None, "") else None
        if name is not None and not 1 <= len(name) <= 60:
            raise ValueError("Give the topic a name under 60 characters.")
        topic = database.create_topic_from_proposal(card["data"]["proposal_id"], name)
        detail["topic_id"] = topic and topic["id"]
        detail["picked"] = topic and topic["name"]
    elif action == "never":
        database.decline_proposal(card["data"]["proposal_id"], never=True)
    elif action == "not_now" and card["kind"] == "proposal":
        database.decline_proposal(card["data"]["proposal_id"])
    elif action == "yes":
        database.update_memory(card["data"]["fact_id"], status="confirmed")
    elif action == "no":
        database.delete_memory(card["data"]["fact_id"])
    elif action == "move":
        task = database.apply_plan_update(card["data"]["plan_update_id"])
        detail["task_id"] = task and task["id"]
    elif action == "different":
        task = database.decline_plan_update(card["data"]["plan_update_id"])
        detail["task_id"] = task and task["id"]
    elif action == "pick":
        raise ValueError("That isn't one of this question's answers.")

    database.record_captain_answer(
        card_id, card["kind"], action if action != "pick" else f"picked:{value}", detail,
        item_id=card["item_id"], task_id=card["task_id"], topic_id=card["topic_id"],
    )
    return needs_you()
