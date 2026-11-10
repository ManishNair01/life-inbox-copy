"""The weekly review, topic proposals, bot summaries and Captain's greeting (change 020).

- **Weekly review: one AI call per user per week**, run by the scheduler, or
  after your first visit once 7 days have passed. Code first expires past
  plans and gathers: your memory facts, Scout's answers this week, and groups
  of 3+ notes in one area that share words no topic covers. The call:
  - merges duplicate facts and trims outdated ones (by id; code checks every id),
  - suggests up to 3 facts for you to confirm ("You organise college events,
    right? Yes / No / Edit"), never a secret, health only with consent,
  - names and describes each note group as a topic proposal.
  Code checks each proposal: no topic with a similar name, its parent is one
  of the area's main topics, 3+ real notes support it, and you never said
  "Don't suggest this" to the same group. A proposal never makes a topic by
  itself (P1): Captain asks "Create it / Rename / Not now / Don't suggest this".
- **Bot summaries**: an area's two-sentence summary is saved with a key of what
  the area held; it's rewritten (one call) only after the area changes.
- **Captain's greeting (decision N)**: one AI call per user per day, saved and
  reused; until it exists (or without AI), the greeting is written by code.

Every AI call here is skipped when no AI is configured or your AI switch is off.
Background work runs after the page has its answer, so nothing waits for it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import bots, database, llm

logger = logging.getLogger(__name__)

REVIEW_DAYS = 7
MAX_FACTS_SENT = 40
MAX_GROUPS = 3
MIN_GROUP = 3
MAX_NEW_FACTS = 3
_STOP = frozenset(
    "the and for with that this from your you are was have has had not but all any can her his its our out "
    "she they them then than too very will just about into over under when what which who why how also some "
    "more most other such only own same so to of in on at by an a is it be as or if do my me we i get got "
    "need want make take buy call note notes idea ideas thing things today tomorrow week next new".split()
)
_running: set[tuple[int, str]] = set()
_guard = threading.Lock()


def _ai_allowed(user_id: int) -> bool:
    if not llm.is_configured():
        return False
    return bool(database.get_settings(user_id).get("ai_processing", True))


def _once(user_id: int, kind: str):
    """At most one of each background job per user at a time."""
    class _Slot:
        def __enter__(self):
            with _guard:
                if (user_id, kind) in _running:
                    return False
                _running.add((user_id, kind))
                return True

        def __exit__(self, *_exc):
            with _guard:
                _running.discard((user_id, kind))
            return False

    return _Slot()


def _as(user_id: int):
    """Run as this user (background jobs have no request)."""
    class _Owner:
        def __enter__(self):
            self.before = database.get_current_owner_id()
            database.set_current_owner_id(user_id)

        def __exit__(self, *_exc):
            database.set_current_owner_id(self.before)
            return False

    return _Owner()


def _words(text: Optional[str]) -> set[str]:
    return {word for word in re.findall(r"[a-z]+", (text or "").lower()) if len(word) > 3 and word not in _STOP}


# --- the weekly review ------------------------------------------------------------------------


def review_due(settings: dict, now: Optional[datetime] = None) -> bool:
    current = now or datetime.now(timezone.utc)

    def parse(stamp):
        try:
            value = datetime.fromisoformat(stamp) if stamp else None
        except ValueError:
            return None
        return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)

    last = parse(settings.get("last_weekly_review_at"))
    if last is not None:
        return current - last >= timedelta(days=REVIEW_DAYS)
    joined = parse(settings.get("created_at"))
    return joined is None or current - joined >= timedelta(days=REVIEW_DAYS)


def note_groups(facts: dict) -> list[dict]:
    """Groups of 3+ notes in one area that share a word no topic of that area
    covers (code only). The biggest first, at most MAX_GROUPS."""
    topics = [t for t in facts["topics"] if not t.get("archived")]
    covered: dict[str, set[str]] = defaultdict(set)
    for topic in topics:
        covered[topic.get("bot_key")] |= _words(f"{topic['name']} {topic.get('description') or ''}")
    by_bot: dict[str, list[dict]] = defaultdict(list)
    for note in facts["notes"]:
        if note.get("bot_key") and not note.get("secret"):
            by_bot[note["bot_key"]].append(note)
    groups, never = [], set(facts.get("never") or ())
    for bot_key, notes in by_bot.items():
        counts = Counter(word for note in notes for word in _words(note["text"]))
        for word, count in counts.most_common():
            if count < MIN_GROUP:
                break
            if word in covered[bot_key]:
                continue
            members = [note for note in notes if word in _words(note["text"])]
            signature = f"{bot_key}:{word}"
            if signature in never or signature in (facts.get("pending_signatures") or ()):
                continue
            if any(set(n["id"] for n in members) <= set(g["item_ids"]) for g in groups):
                continue
            groups.append({"group": f"g{len(groups) + 1}", "bot_key": bot_key, "word": word, "signature": signature,
                           "item_ids": [n["id"] for n in members][:8], "titles": [n["title"] for n in members][:5]})
    groups.sort(key=lambda g: -len(g["item_ids"]))
    return groups[:MAX_GROUPS]


def _main_topics(facts: dict, bot_key: str) -> list[dict]:
    return [t for t in facts["topics"] if t.get("bot_key") == bot_key and not t.get("parent_topic_id") and not t.get("archived")]


def _similar(name: str, topics: list[dict]) -> bool:
    words = _words(name) or {name.lower()}
    for topic in topics:
        other = topic["name"].lower()
        if other == name.lower() or (words and words <= _words(other)) or (_words(other) and _words(other) <= words):
            return True
    return False


def build_prompt(facts: dict, groups: list[dict]) -> str:
    memory = [{"id": f"m{f['id']}", "fact": f["text"], "status": f["status"]} for f in facts["memory"][:MAX_FACTS_SENT]]
    events = [{"id": f"e{e['id']}", "what": e["line"]} for e in facts["events"][:20]]
    areas = {bot.key: bot.name for bot in bots.BOTS}
    proposal_groups = [{
        "group": g["group"], "area": areas.get(g["bot_key"], g["bot_key"]),
        "main_topics": [t["name"] for t in _main_topics(facts, g["bot_key"])],
        "shared_word": g["word"], "notes": g["titles"],
    } for g in groups]
    return f"""You tidy a personal Life Inbox's memory once a week.

Memory facts (JSON; "suggested" ones aren't confirmed yet):
{json.dumps(memory, ensure_ascii=False)}

What the user did this week (JSON):
{json.dumps(events, ensure_ascii=False)}

Groups of notes that no topic fits yet (JSON):
{json.dumps(proposal_groups, ensure_ascii=False)}

Answer with ONLY this JSON:
{{"merge": [{{"keep": "m1", "drop": ["m4"]}}], "trim": ["m7"],
  "new_facts": [{{"fact": "You organise college events", "from": ["m3", "e2"]}}],
  "proposals": [{{"group": "g1", "name": "Hostel life", "description": "one short sentence", "parent": "Home & errands"}}]}}
- "merge": facts that say the same thing; keep the clearest. "trim": facts no longer true.
- "new_facts": up to 3 short, lasting facts the user's own facts and actions plainly show. Never a
  guess, never a secret, never a health detail. The user is asked before any is kept.
- "proposals": a short name (2-4 words) and description for a group, and its parent: one of that
  group's "main_topics", copied exactly. Leave out a group that isn't one clear subject.
- Use only the ids and groups above. Empty lists are fine.
"""


def check_review(data: dict, facts: dict, groups: list[dict]) -> tuple[Optional[str], dict]:
    if not isinstance(data, dict):
        return "The answer must be one JSON object.", {}
    known = {f"m{f['id']}": f for f in facts["memory"]}
    events = {f"e{e['id']}" for e in facts["events"]}
    by_group = {g["group"]: g for g in groups}
    out = {"merge": [], "trim": [], "new_facts": [], "proposals": []}
    for merge in data.get("merge") or []:
        if not isinstance(merge, dict) or merge.get("keep") not in known:
            return "Every merge needs a \"keep\" id from the facts.", {}
        drops = [d for d in merge.get("drop") or [] if d in known and d != merge["keep"]]
        if drops:
            out["merge"].append({"keep": known[merge["keep"]]["id"], "drop": [known[d]["id"] for d in drops]})
    out["trim"] = [known[t]["id"] for t in data.get("trim") or [] if t in known]
    from app.sensitive import looks_secret

    for fact in (data.get("new_facts") or [])[:MAX_NEW_FACTS]:
        text = str((fact or {}).get("fact") or "").strip()[:160] if isinstance(fact, dict) else ""
        sources = [s for s in (fact.get("from") or []) if s in known or s in events] if isinstance(fact, dict) else []
        if text and sources and not looks_secret(text):
            items = sorted({i for s in sources if s in known for i in known[s]["source_item_ids"]})
            out["new_facts"].append({"text": text, "item_ids": items})
    for proposal in data.get("proposals") or []:
        if not isinstance(proposal, dict) or proposal.get("group") not in by_group:
            continue
        group = by_group[proposal["group"]]
        name = " ".join(str(proposal.get("name") or "").split())[:60].strip(" .")
        parents = {t["name"].lower(): t for t in _main_topics(facts, group["bot_key"])}
        parent = parents.get(str(proposal.get("parent") or "").strip().lower())
        all_topics = [t for t in facts["topics"] if not t.get("archived")]
        if not name or parent is None or _similar(name, all_topics) or len(group["item_ids"]) < MIN_GROUP:
            continue  # code's checks: a real, new subtopic of one main topic, with 3+ notes
        if any(name.lower() == p["name"].lower() for p in facts.get("pending") or ()):
            continue
        out["proposals"].append({"bot_key": group["bot_key"], "name": name,
                                 "description": str(proposal.get("description") or "").strip()[:200] or None,
                                 "parent_topic_id": parent["id"], "item_ids": group["item_ids"],
                                 "signature": group["signature"]})
    return None, out


def run_weekly(user_id: int, *, now: Optional[datetime] = None, force: bool = False) -> Optional[dict]:
    """The weekly review for one user (one AI call). None when not due or no AI."""
    with _once(user_id, "weekly") as free, _as(user_id):
        if not free:
            return None
        settings = database.get_settings(user_id)
        if not force and not review_due(settings, now):
            return None
        if not _ai_allowed(user_id):
            return None
        facts = database.review_facts(user_id)
        groups = note_groups(facts)
        if not facts["memory"] and not facts["events"] and not groups:
            database.update_settings(user_id, last_weekly_review_at=(now or datetime.now(timezone.utc)).isoformat())
            return {"skipped": "nothing to review"}
        checked: dict = {}

        def validate(data: dict) -> Optional[str]:
            problem, fields = check_review(data, facts, groups)
            if problem:
                return problem
            checked.update(fields)
            return None

        try:
            llm.complete_json("weekly_review", build_prompt(facts, groups), validate=validate, repair=True)
        except Exception:
            logger.exception("Weekly review failed for user %s", user_id)
            return None
        result = database.save_review(user_id, checked)
        database.update_settings(user_id, last_weekly_review_at=(now or datetime.now(timezone.utc)).isoformat())
        return result


def run_due_reviews(now: Optional[datetime] = None) -> int:
    """For the scheduler: every user whose review is due (one call each)."""
    done = 0
    for user_id in database.list_user_ids():
        try:
            if run_weekly(user_id, now=now):
                done += 1
        except Exception:
            logger.exception("Weekly review failed for user %s", user_id)
    return done


# --- bot summaries ------------------------------------------------------------------------------


def code_summary(area: dict) -> str:
    bot = bots.BOTS_BY_KEY[area["bot_key"]]
    if not area["notes"] and not area["tasks"]:
        return f"Nothing in {bot.name} yet. Notes about it will gather here."
    parts = [f"{len(area['notes'])} note{'s' if len(area['notes']) != 1 else ''}"]
    if area["tasks"]:
        parts.append(f"{len(area['tasks'])} open task{'s' if len(area['tasks']) != 1 else ''}")
    return " · ".join(parts) + "."


def summary_key(area: dict) -> str:
    raw = json.dumps([[n["id"], n["updated"]] for n in area["notes"]] + [[t["id"], t["day"]] for t in area["tasks"]])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def bot_summary(bot_key: str, user_id: int) -> dict:
    """The saved summary if the area hasn't changed; else code's, and whether
    a rewrite (one call) should run in the background."""
    area = database.bot_area(bot_key, user_id)
    key = summary_key(area)
    saved = database.get_bot_summary(bot_key, user_id)
    if saved and saved["data_key"] == key:
        return {"summary": saved["summary"], "ai": True, "rewrite": False}
    return {"summary": code_summary(area), "ai": False, "rewrite": _ai_allowed(user_id) and bool(area["notes"])}


def rewrite_summary(bot_key: str, user_id: int) -> Optional[str]:
    with _once(user_id, f"summary:{bot_key}") as free, _as(user_id):
        if not free or not _ai_allowed(user_id):
            return None
        area = database.bot_area(bot_key, user_id)
        key = summary_key(area)
        saved = database.get_bot_summary(bot_key, user_id)
        if saved and saved["data_key"] == key:
            return saved["summary"]
        bot = bots.BOTS_BY_KEY[bot_key]
        prompt = f"""Write the summary line for the "{bot.name}" area of a personal Life Inbox.

Notes in it (titles, newest first; JSON): {json.dumps([n["title"] for n in area["notes"][:15]], ensure_ascii=False)}
Open tasks (JSON): {json.dumps([{"task": t["text"], "day": t["day"]} for t in area["tasks"][:8]], ensure_ascii=False)}

Answer with ONLY this JSON: {{"summary": "two short, warm sentences about what's here and what's next"}}
Use only what's listed. No advice, no invented facts, under 240 characters."""
        text: dict = {}

        def validate(data: dict) -> Optional[str]:
            value = " ".join(str((data or {}).get("summary") or "").split())
            if not value or len(value) > 280:
                return "\"summary\" must be one or two sentences under 240 characters."
            text["value"] = value
            return None

        try:
            llm.complete_json("bot_summary", prompt, validate=validate, repair=True)
        except Exception:
            logger.exception("Bot summary failed for user %s area %s", user_id, bot_key)
            return None
        database.save_bot_summary(bot_key, text["value"], key, user_id)
        return text["value"]


# --- Captain's greeting (decision N: AI, once a day) --------------------------------------------


def code_greeting(info: dict) -> str:
    parts = []
    if info["needs"]:
        parts.append(f"{info['needs']} thing{'s' if info['needs'] != 1 else ''} need{'s' if info['needs'] == 1 else ''} you")
    if info["today"]:
        parts.append(f"{len(info['today'])} due today")
    return (", ".join(parts).capitalize() + ".") if parts else "Nothing urgent today."


def greeting(user_id: int, day: str) -> dict:
    saved = database.get_greeting(day, user_id)
    if saved:
        return {"text": saved, "ai": True, "write": False}
    info = database.greeting_facts(user_id)
    return {"text": code_greeting(info), "ai": False, "write": _ai_allowed(user_id)}


def write_greeting(user_id: int, day: str) -> Optional[str]:
    with _once(user_id, "greeting") as free, _as(user_id):
        if not free or not _ai_allowed(user_id) or database.get_greeting(day, user_id):
            return None
        info = database.greeting_facts(user_id)
        prompt = f"""Write Captain's one-line greeting for a personal Life Inbox, for {info['weekday']}.

What's on (JSON): {json.dumps({"needs_you": info["needs"], "due_today": info["today"][:3], "coming_up": info["soon"][:3]}, ensure_ascii=False)}

Answer with ONLY this JSON: {{"greeting": "one warm, plain sentence under 140 characters"}}
Mention at most one task by its words above. No advice, no emoji, no invented facts."""
        text: dict = {}

        def validate(data: dict) -> Optional[str]:
            value = " ".join(str((data or {}).get("greeting") or "").split())
            if not value or len(value) > 160 or "http" in value.lower():
                return "\"greeting\" must be one sentence under 140 characters, no links."
            text["value"] = value
            return None

        try:
            llm.complete_json("greeting", prompt, validate=validate, repair=True)
        except Exception:
            logger.exception("Greeting failed for user %s", user_id)
            return None
        database.save_greeting(day, text["value"], user_id)
        return text["value"]
