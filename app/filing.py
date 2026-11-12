"""Filing v2 (change 014): one checked AI call per note.

The grounding ladder (design section 4.2):

- Level 0, code (free): the rules R1-R6 in order with keywords, similar past
  notes from search, and your topic words pick the 1-2 likely life areas.
- Level 1, one call: the instructions and rules, today's date and time zone,
  the five areas and their topics (full descriptions for the likely areas,
  names for the rest), your words kept apart from the source (cut to 1,500
  characters), and up to 3 similar notes marked "filed by you" or "by AI".
- Level 2, code checks: the topic exists and belongs to that area, every date
  is a real date, the answer covers exactly these notes.
- Level 3: one repair call that names the failed check (llm.complete_json),
  then the offline matcher.
- Level 4: unsure or tied, the note waits in Captain's "Needs you" list with
  its two likeliest topics. It gets no topic until you pick (rule R6).

There is no catch-all: unclear notes wait for you. Notes saved while a call
runs share the next one, up to 5 (decision G). "Re-sort everything" files at
most 25 notes per call, only when you ask.

Memory (change 017, behind LIFE_INBOX_MEMORY_IN_FILING=1): the call also gets
"What Life Inbox knows": your next plans (8), your core profile (5) and up to
15 confirmed facts that share words or an area with the notes, within 1,800
characters. Hints only; the note's own words win. The answer says which hints
it used ("memory_used", saved on the note) and whether the note moves one of
your plans ("plan_update", asked in Needs you before anything changes).
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
from collections import defaultdict
from typing import Optional

from app import bots, database, llm
from app.attention.dates import configured_timezone, today_in_configured_tz
from app.organizer import (
    CATCH_ALL_TOPIC,
    _keyword_hits,
    _split_action_tasks,
    _tags_for_text,
    _topic_keywords,
    priority_for_text,
    topic_choices,
)

logger = logging.getLogger(__name__)

MAX_BATCH = 5
RESORT_BATCH = 25
WORDS_LIMIT = 2000
SOURCE_LIMIT = 1500
PROMPT_LIMIT_CHARS = 12_000  # about 3,000 tokens (build plan section 6)
PROMPT_LIMIT_TOKENS = 3_200  # the gateway's hard stop, a little above
SIMILAR_LIMIT = 3
RULES = ("R1", "R2", "R3", "R4", "R5", "R6")
MEMORY_FLAG = "LIFE_INBOX_MEMORY_IN_FILING"
MEMORY_LIMIT_CHARS = 1_800
PLANS_LIMIT = 8
CORE_LIMIT = 5
HINTS_LIMIT = 15
_STOP = frozenset(
    "the and for with that this from your you are was have has had not but all any can her his its our out "
    "she they them then than too very will just about into over under when what which who why how also some "
    "more most other such only own same so to of in on at by an a is it be as or if do my me we i".split()
)
INTENTS = ("commitment", "tentative", "someday")
# Offline reading of intent (change 014a): a wish or a maybe isn't a commitment.
_SOMEDAY = re.compile(r"\b(some ?day|one day|next time|whenever|bucket list|would love to|wish (i|to)|"
                      r"when i (will )?(travel|go|visit|am|'m) |want to (visit|try|go|see|learn|read|watch))", re.I)
_TENTATIVE = re.compile(r"\b(should (probably )?|probably|maybe|might|thinking (of|about)|plan(ning)? to|"
                        r"could|ought to|need to think|perhaps)\b", re.I)


def offline_intent(text: str) -> str:
    """commitment, tentative or someday, from the words alone."""
    if _SOMEDAY.search(text or ""):
        return "someday"
    if _TENTATIVE.search(text or ""):
        return "tentative"
    return "commitment"
CONFIDENCE = ("high", "medium", "low")
PRIORITIES = ("High", "Medium", "Low")

# Design section 4.1, word for word. The filing prompt includes them.
RULES_TEXT = """\
R1. Anything medical goes to Health, including family members'. Example: "Pick up Dad's prescription" -> Medicines & doctors.
R2. Your own bills, subscriptions, fees and paperwork go to Money & home. One-off purchases for a plan (a gift, a trip booking) don't count. Example: "Cancel Netflix on 15 Dec" -> Bills & subscriptions.
R3. The purpose in your note beats the content. Example: Pasta recipe "for my date" -> People > Occasions & gifts.
R4. A college's or employer's money and tasks go to Learning & work. Example: Halloween event budget -> Study.
R5. Otherwise the subject decides, not the format; a video or PDF is only a container. Example: Hypothesis Testing PDF -> Study.
R6. Still unclear -> don't guess. Give the top two choices and confidence "low"."""

RULE_SHORT = {
    "R1": "Anything medical goes to Health",
    "R2": "Your own bills, subscriptions and paperwork go to Money & home",
    "R3": "The purpose in your note beats the content",
    "R4": "A college's or employer's money and tasks go to Learning & work",
    "R5": "The subject decides, not the format",
    "R6": "Unclear, so Life Inbox asks you",
}

# --- Level 0 and the offline matcher: the rules, by code -------------------------------
# Each entry: (rule, topic, whole-word pattern on the lower-cased text). Checked
# in order; the first that fits decides (design section 4.1).
_PET = re.compile(r"\b(vets?|pets?|puppy|kitten|rabies|deworm\w*|dog food|cat food)\b")
# An idea to build mentions bills or subscriptions without being yours (not R2).
_IDEA = re.compile(r"\b((app|startup|business|product|project) ideas?|ideas? for an? (app|startup|business))\b|^\s*ideas?\s*:")
_QUOTE = re.compile(r"^\s*[\"“'‘].{8,}[\"”'’]\s*(\(|[-–—])")
RULE_PATTERNS: tuple[tuple[str, str, re.Pattern], ...] = tuple(
    (rule, topic, re.compile(pattern))
    for rule, topic, pattern in (
        ("R1", "Mind & mood", r"\b(therap(y|ist)|counsel(l)?(or|ing)|anxiety|anxious|depress\w*|panic attack|felt low|feel(ing)? low|talk to someone|mental health)\b"),
        ("R1", "Medicines & doctors", r"\b(doctor|dentist|medicines?|medication|meds|pills?|tablets?|doses?|dosage|prescription|pharmacy|chemist|crocin|paracetamol|syrup|cough|fever|vitamins?|hospital|clinic|check-?up|lab test|blood test|thyroid|x-?ray|vaccin\w*|injection|physio\w*)\b"),
        ("R2", "Bills & subscriptions", r"\b(bills?|subscriptions?|netflix|spotify|hotstar|rent|landlord|emi|recharge|electricity|broadband|fees?)\b"),
        ("R2", "Bank, tax & documents", r"\b(tax|taxes|itr|gst|insurance|passport|pan card|aadhaa?r|bank|salary|rd|fd|sip|mutual funds?|invest\w*|loan|kyc|driving licen[cs]e)\b"),
        ("R3", "Occasions & gifts", r"\b(for (my|our) date|date night|birthday|bday|anniversary|wedding|gifts?|valentine\w*)\b"),
        ("R3", "Work & career", r"\b(interview|recruiter|job offer|offer letter|resume|placement|internship)\b"),
        ("R3", "Trips & places", r"\b(visa|pnr|flight|boarding pass|itinerary|hotel|hostel)\b"),
        ("R3", "Study", r"\bfor (my |the )?(statistics|stats|exams?|quiz|class|course|assignment|semester|mid-?sem|finals?)\b"),
        ("R4", "Study", r"\b(my college|our college|college (event|fest|budget|admin|club|committee)|admin team|university|department|hod|professor|campus|halloween event)\b"),
        ("R4", "Work & career", r"\b(office|my company|employer|client|manager|team meeting|stand-?up|reimburse\w*|appraisal|payroll|sprint)\b"),
        ("R5", "Fitness & food", r"\b(workout|gym|squats?|lunges?|push-?ups?|leg day|yoga|running|jog\w*|diet|calories|protein|cardio)\b"),
        ("R5", "Study", r"\b(quiz|exams?|assignment|homework|lecture|syllabus|revision|study|studying|statistics|stats|hypothesis|semester|mid-?sem|course)\b"),
        ("R5", "Family", r"\b(mom|mum|mummy|maa|dad|papa|father|mother|brother|sister|son|daughter|kids?|parent-?teacher|grand(ma|pa|mother|father)|family|nani|dadi)\b"),
        ("R5", "Work & career", r"\b(team|colleagues?|boss|presentation|meetings?|office|work)\b"),
        ("R5", "Friends & partner", r"\b(friends?|partner|girlfriend|boyfriend|wife|husband|rohan)\b"),
        ("R5", "Watch, read & listen", r"\b(watch|read|reading|podcasts?|episode|movie|film|series|documentary|audiobook|album|song|playlist|quotes?)\b"),
        ("R5", "Trips & places", r"\b(trip|travel|holiday|vacation|trek|beach|packing|goa|jaipur|manali|thailand)\b"),
        ("R5", "Home & errands", r"\b(buy|groceries|grocery|milk|eggs|atta|onions?|vegetables|pick up|dry cleaning|laundry|plumber|electrician|leak\w*|repair|wifi password|router|car service|bike service|maid|cleaning|courier|parcel|order)\b"),
        ("R5", "Cooking", r"\b(recipes?|cook|cooking|bake|baking|butter chicken|pasta|biryani|paneer|curry|dish(es)?)\b"),
        ("R5", "Hobbies", r"\b(guitar|piano|painting|knit\w*|chess|hobby|hobbies|craft\w*|sketch\w*|photography|gardening)\b"),
        ("R5", "Skills & projects", r"\b(app idea|startup|side project|ideas?|build|tutorials?|tools?|github|coding|code|python|javascript|ai agents?|llm|nemotron|open source|hackathon|portfolio)\b"),
    )
)


def _topics_by_name(topics: list[dict]) -> dict[str, dict]:
    return {
        topic["name"].lower(): topic
        for topic in topics
        if not topic.get("archived") and topic["name"].lower() != CATCH_ALL_TOPIC.lower()
    }


def own_words(note: dict) -> str:
    """Your words: the note itself, a voice note's transcript, or your note on a source."""
    if note.get("source") in (None, "voice"):
        return (note.get("text") or "").strip()
    return (note.get("context") or "").strip()


def _topic_fit(text: str, topic: dict) -> list[str]:
    """Words showing a note fits one of your topics: a word of its name, or at
    least two of its description ("Learning the Python language" alone mustn't
    pull in every note about learning). Empty when it doesn't fit."""
    lowered = (text or "").lower()
    name_words = _topic_keywords({"name": topic.get("name")})
    from_name = _keyword_hits(lowered, name_words)
    from_description = _keyword_hits(lowered, _topic_keywords({"description": topic.get("description")}) - name_words)
    if from_name:
        return from_name + from_description
    return from_description if len(from_description) >= 2 else []


def _match_rules(text: str, topics: dict[str, dict], user_topics: list[dict]) -> Optional[tuple[str, dict, str]]:
    """(rule, topic, matched words) for the first rule that fits this text,
    narrowed to your own subtopic of that topic when its words fit too."""
    found = _first_rule(text, topics, user_topics)
    if found is None:
        return None
    rule, topic, words = found
    best = None
    for child in user_topics:
        if child.get("parent_topic_id") != topic["id"]:
            continue
        hits = _topic_fit(text, child)
        if hits and (best is None or len(hits) > best[0]):
            best = (len(hits), child)
    return (rule, best[1], words) if best else found


def _first_rule(text: str, topics: dict[str, dict], user_topics: list[dict]) -> Optional[tuple[str, dict, str]]:
    lowered = (text or "").lower()
    if not lowered.strip():
        return None
    if _PET.search(lowered) and "home & errands" in topics:
        return "R5", topics["home & errands"], _PET.search(lowered).group(0)  # pets: household, not Health
    if _IDEA.search(lowered) and "skills & projects" in topics:
        return "R5", topics["skills & projects"], _IDEA.search(lowered).group(0).strip(" :")
    for rule, name, pattern in RULE_PATTERNS:
        if rule == "R5" and user_topics:
            break
        found = pattern.search(lowered)
        if found and name.lower() in topics:
            return rule, topics[name.lower()], found.group(0)
    if user_topics:
        # Your own topics come before the default subjects (R5).
        best = None
        for topic in user_topics:
            hits = _topic_fit(lowered, topic)
            rank = (len(hits), topic.get("parent_topic_id") is not None)
            if hits and (best is None or rank > best[0]):
                best = (rank, topic, hits[0])
        if best:
            return "R5", best[1], best[2]
        for rule, name, pattern in RULE_PATTERNS:
            if rule != "R5":
                continue
            found = pattern.search(lowered)
            if found and name.lower() in topics:
                return rule, topics[name.lower()], found.group(0)
    if _QUOTE.search(text) and "watch, read & listen" in topics:
        return "R5", topics["watch, read & listen"], "a quote"
    return None


def offline_file(note: dict, topics: list[dict]) -> dict:
    """File one note without AI, by the rules in order. Your words are read
    first (R3: your purpose beats the content). Nothing fits: no guess, the
    note waits in Needs you with its two likeliest topics (R6)."""
    by_name = _topics_by_name(topics)
    user_topics = [t for t in by_name.values() if not t.get("is_built_in") and t.get("origin") != "built_in"]
    words = own_words(note)
    source = (note.get("text") or "") if note.get("source") not in (None, "voice") else ""
    title_from = note.get("source_title") or words or source
    match = None
    from_words = False
    if words and source:
        match = _match_rules(words, by_name, user_topics)
        from_words = match is not None
    if match is None:
        match = _match_rules(f"{words}\n{source}".strip(), by_name, user_topics)
    everything = f"{words}\n{source}".strip()
    priority = priority_for_text(everything)
    result = {
        "id": note["id"],
        "title": _title(title_from),
        "priority": priority,
        "tags": _tags_for_text(everything),
        "tasks": [
            {"task": todo["task"], "when": todo.get("when"), "date": None, "time": None,
             "intent": offline_intent(todo["task"])}
            for todo in (_split_action_tasks(words, note["id"], priority) if words else [])
        ],
        "summary": None,
        "action": None,
        "transcript": None,
        "filed_by": "offline",
    }
    if match is None:
        choices = topic_choices(everything, list(by_name.values()), limit=2)
        result.update(
            topic=None, bot=None, rule="R6", confidence="low", choices=[c["id"] for c in choices],
            reason="Life Inbox couldn't tell where this goes, so it asks you.",
        )
        return result
    rule, topic, found = match
    if from_words and rule == "R5":
        rule = "R3"  # the subject came from your own words: your purpose
    result.update(
        topic=topic["id"], bot=topic.get("bot_key"), rule=rule,
        confidence="high" if rule in ("R1", "R2", "R3", "R4") else "medium", choices=[],
        reason=f"{RULE_SHORT[rule]}: {'your note says' if from_words else 'it mentions'} “{found}”.",
    )
    return result


def _title(text: Optional[str]) -> str:
    flat = " ".join(str(text or "").split()) or "Untitled note"
    return flat if len(flat) <= 72 else flat[:71].rstrip() + "…"


def likely_bots(note: dict, topics: list[dict]) -> list[str]:
    """The 1-2 life areas a note most likely belongs to (code only)."""
    found = []
    first = offline_file(note, topics)
    if first.get("bot"):
        found.append(first["bot"])
    for topic in topic_choices(f"{own_words(note)} {note.get('text') or ''}", topics, limit=3):
        if topic.get("bot_key") and topic["bot_key"] not in found:
            found.append(topic["bot_key"])
    return found[:2]


def similar_notes(note: dict) -> list[dict]:
    """Up to 3 notes like this one, with how they're filed ("by you" or "by AI")."""
    from app.retrieval.search import search_passages

    query = f"{own_words(note)} {(note.get('text') or '')[:300]}".strip()
    if not query:
        return []
    try:
        ids = []
        for hit in search_passages(query, limit=10):
            item_id = hit.passage.item_id
            if item_id != note["id"] and item_id not in ids:
                ids.append(item_id)
        examples = database.filing_examples(ids)
    except Exception:
        # Similar notes are a hint; filing goes on without them.
        logger.exception("Similar-note search failed")
        return []
    return [examples[item_id] for item_id in ids if item_id in examples][:SIMILAR_LIMIT]


# --- Memory: what Life Inbox knows (change 017) -------------------------------------------


def memory_on() -> bool:
    """Memory in filing is off until the owner OKs the live replay (decision log)."""
    return os.environ.get(MEMORY_FLAG, "").strip() == "1"


def _content_words(text: Optional[str]) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(word) > 2 and word not in _STOP}


def memory_pack(notes: list[dict], topics: list[dict]) -> Optional[dict]:
    """The hints the filing call gets: plans, core profile, and the facts that
    share words or an area with these notes. Only confirmed facts; never a
    secret (memory never holds one); health only with consent (list_memory)."""
    if not notes:
        return None
    known = database.memory_for_filing()
    words: set[str] = set()
    likely: set[str] = set()
    for note in notes:
        words |= _content_words(f"{own_words(note)} {note.get('source_title') or ''} {(note.get('text') or '')[:300]}")
        likely.update(likely_bots(note, topics))
    plans = [{"id": f"p{plan['task_id']}", "task": _cut(plan["text"], 80), "day": plan["due_on"],
              **({"time": plan["due_time"]} if plan.get("due_time") else {})}
             for plan in known["plans"][:PLANS_LIMIT]]
    core = [fact for fact in known["facts"] if fact["core_profile"]][:CORE_LIMIT]
    scored = []
    for fact in known["facts"]:
        if fact["core_profile"] or fact["kind"] == "short_term":
            continue  # core facts go in "about_you"; plans come from your tasks
        score = 2 * len(_content_words(fact["text"]) & words) + (1 if fact.get("bot_key") in likely else 0)
        if score:
            scored.append((-score, -fact["times_seen"], -fact["id"], fact))
    hints = [fact for *_, fact in sorted(scored, key=lambda row: row[:3])][:HINTS_LIMIT]
    pack = {
        "coming_up": plans,
        "about_you": [{"id": f"m{fact['id']}", "fact": fact["text"]} for fact in core],
        "hints": [{"id": f"m{fact['id']}", "fact": fact["text"]} for fact in hints],
    }
    import json

    for part in ("hints", "coming_up", "about_you"):  # trim to the size cap, least useful first
        while pack[part] and len(json.dumps(pack, ensure_ascii=False)) > MEMORY_LIMIT_CHARS:
            pack[part].pop()
    if not any(pack.values()):
        return None
    pack["_texts"] = {entry["id"]: entry.get("fact") or f"{entry['task']} ({entry['day']})"
                      for part in ("coming_up", "about_you", "hints") for entry in pack[part]}
    pack["_plans"] = {f"p{plan['task_id']}": plan for plan in known["plans"][:PLANS_LIMIT]}
    return pack


def _pack_for_prompt(pack: dict) -> dict:
    return {key: value for key, value in pack.items() if not key.startswith("_") and value}


# --- Level 1: the prompt -----------------------------------------------------------------


def _areas_section(topics: list[dict], likely: set[str]) -> list[dict]:
    by_bot: dict[Optional[str], list[dict]] = defaultdict(list)
    for topic in _topics_by_name(topics).values():
        by_bot[topic.get("bot_key")].append(topic)
    areas = []
    for bot in bots.BOTS:
        entries = []
        for topic in sorted(by_bot.get(bot.key, []), key=lambda t: (t.get("parent_topic_id") is not None, t["id"])):
            entry = {"topic": topic["name"]}
            if topic.get("parent_topic_id"):
                parent = next((t for t in topics if t["id"] == topic["parent_topic_id"]), None)
                if parent:
                    entry["under"] = parent["name"]
            if (bot.key in likely or not likely) and topic.get("description"):
                entry["about"] = topic["description"][:160]
            entries.append(entry)
        areas.append({"area": bot.key, "name": bot.name, "topics": entries})
    return areas


def _cut(text: Optional[str], limit: int) -> str:
    flat = (text or "").strip()
    return flat if len(flat) <= limit else flat[: max(0, limit - 1)].rstrip() + "…"


def build_prompt(notes: list[dict], topics: list[dict], *, compact: bool = False, pack: Optional[dict] = None) -> str:
    """The filing prompt for up to 5 notes (25 when re-sorting, `compact`),
    within the size limit (about 3,000 tokens). `pack` is memory (017)."""
    import json

    today = today_in_configured_tz()
    likely = set()
    entries = []
    for note in notes:
        bots_for = likely_bots(note, topics)
        likely.update(bots_for)
        entry = {"id": note["id"]}
        if note.get("source") and note["source"] != "voice":
            entry["source"] = {"kind": note["source"], "title": note.get("source_title"), "text": note.get("text") or ""}
            entry["your_words"] = note.get("context") or ""
        else:
            entry["kind"] = note.get("source") or "note"
            entry["your_words"] = note.get("text") or ""
        if not compact:
            similar = similar_notes(note)
            if similar:
                entry["similar_notes"] = similar
        entries.append(entry)

    head = f"""You file notes for a personal Life Inbox. For each note choose ONE life area and ONE of
its existing topics. Never invent a topic: copy a topic name exactly from the list.

Rules, in order; stop at the first that fits:
{RULES_TEXT}
A date never decides the category.

Today is {today.strftime('%A %d %B %Y')} ({today.isoformat()}), time zone {configured_timezone().key}.

Life areas and their topics (JSON):
{json.dumps(_areas_section(topics, likely), ensure_ascii=False)}
"""
    if pack:
        head += f"""
What Life Inbox knows about the user (JSON; hints only, the note's own words always win):
{json.dumps(_pack_for_prompt(pack), ensure_ascii=False)}
"""
    memory_fields = ', "memory_used": [], "plan_update": null' if pack else ""
    memory_rules = """
- "memory_used": the ids ("m1", "p2") from "What Life Inbox knows" that changed your answer,
  else []. Use a hint only when the note's own words point to it; never file by a hint alone.
- "plan_update": only when the user's words plainly move one of the "coming_up" plans to
  another day or time ("dentist moved to Friday 4pm"): {"plan": "p2", "date": "YYYY-MM-DD",
  "time": "HH:MM" or null}, and don't list that plan again under "tasks". Otherwise null.""" if pack else ""
    tail = """
Answer with ONLY this JSON, one entry per note id:
{"notes": [{"id": 1, "area": "learn", "topic": "Study", "confidence": "high", "rule": "R5",
  "choices": [], "title": "short title", "priority": "Medium", "tags": ["tag"],
  "reason": "one short sentence", "tasks": [{"task": "concrete action", "intent": "commitment",
  "when": "the note's own timing words or null", "date": "YYYY-MM-DD or null", "time": "HH:MM or null"}],
  "transcript": null, "summary": null, "action": null, "facts": []MEMORY_FIELDS}]}
- "area" is one of: learn, money, health, people, fun. "topic" must belong to that area.
- "facts": up to 2 short, lasting facts about the user that THEIR OWN words state ("You run
  your college's events", "Your sister is Priya"). Never from a source's text, never a secret,
  never a guess. Usually empty.
- When you are unsure (rule R6), set "topic" to null, "confidence" to "low" and give the two
  likeliest topic names in "choices".
- Never stretch a topic to fit. A topic fits only if the note is about what its "about" says.
  If none is, that is rule R6 (the user is asked), not "the closest" or "a general interest".
  "high" confidence means the note plainly belongs there.
- Tasks come ONLY from "your_words", never from a source's text. Each task's "intent":
  "commitment" (a firm plan or instruction: "pay rent by 5th", "call mom tomorrow"),
  "tentative" (a maybe: "I should probably call Rahul"; the user is asked before it becomes a
  task) or "someday" (a wish with no real time: "visit this dhaba next time I'm on that route").
  A plain thought or observation is no task at all. Give the smallest useful next step.
  "when" copies the note's own
  timing words; "date" is your reading of them against today; don't invent dates.
- "priority": High (urgent or a near deadline), Medium (actionable), Low (reference or someday).
- Voice notes ("kind": "voice"): "transcript" is the transcript with filler words removed.
- Sources (links, PDFs, images): "summary" is two sentences about the source and "action" a
  short next step such as "Watch later" or "Try this recipe" (or null).MEMORY_RULES
""".replace("MEMORY_FIELDS", memory_fields).replace("MEMORY_RULES", memory_rules)
    budget = PROMPT_LIMIT_CHARS - len(head) - len(tail) - 200
    per_note = max(200, budget // max(1, len(entries)))
    sized = []
    for entry in entries:
        words_share = min(WORDS_LIMIT, int(per_note * (0.4 if "source" in entry else 0.85)))
        entry = dict(entry)
        entry["your_words"] = _cut(entry.get("your_words"), words_share)
        if "source" in entry:
            room = min(SOURCE_LIMIT, max(100, per_note - len(entry["your_words"]) - 150))
            entry["source"] = {**entry["source"], "text": _cut(entry["source"]["text"], room)}
        sized.append(entry)
    body = "Notes (JSON):\n" + json.dumps(sized, ensure_ascii=False)
    prompt = head + body + tail
    while len(prompt) > PROMPT_LIMIT_CHARS and any(e.get("similar_notes") for e in sized):
        for entry in sized:
            entry.pop("similar_notes", None)
        prompt = head + "Notes (JSON):\n" + json.dumps(sized, ensure_ascii=False) + tail
    return prompt


# --- Level 2: code checks ------------------------------------------------------------------


def _clean_name(name) -> str:
    """ "“Recipes”", "Skills & projects: Self-directed learning..." and "recipes
    (subtopic)" all mean the topic's name; a repair call isn't needed for that."""
    cleaned = str(name or "").strip().strip("\"'“”‘’").strip()
    for mark in (": ", " - ", " — ", " ("):
        if mark in cleaned:
            cleaned = cleaned.split(mark, 1)[0]
    return cleaned.strip().strip("\"'“”‘’").strip().lower()


def _memory_fields(entry: dict, pack: Optional[dict], tasks: list[dict]) -> tuple[list[dict], Optional[dict]]:
    """The hints the answer says it used (unknown ids dropped), and a plan it
    moves (checked: a known plan, a real new day). Never a repair reason."""
    from datetime import date

    if not pack:
        return [], None
    used = []
    for hint in entry.get("memory_used") or [] if isinstance(entry.get("memory_used"), list) else []:
        hint = str(hint).strip()
        if hint in pack["_texts"] and hint not in [u["id"] for u in used]:
            used.append({"id": hint, "text": pack["_texts"][hint]})
    update = entry.get("plan_update")
    if not isinstance(update, dict):
        return used[:5], None
    plan = pack["_plans"].get(str(update.get("plan") or "").strip())
    day, clock = update.get("date"), update.get("time") or None
    try:
        date.fromisoformat(str(day))
    except ValueError:
        return used[:5], None
    if plan is None or (clock and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(clock))):
        return used[:5], None
    if day == plan["due_on"] and (clock or None) == (plan.get("due_time") or None):
        return used[:5], None
    # The note's own version of that task is the update, not a second task.
    plan_words = _content_words(plan["text"])
    same = next((task for task in tasks if plan_words and len(_content_words(task["task"]) & plan_words) * 2 >= len(plan_words)), None)
    if same is not None:
        tasks.remove(same)
    return used[:5], {"task_id": plan["task_id"], "task_text": plan["text"], "date": day, "time": clock,
                      "new_task_text": same["task"] if same else plan["text"],
                      "when": (same or {}).get("when")}


def check_answer(data: dict, notes: list[dict], topics: list[dict], pack: Optional[dict] = None) -> tuple[dict[int, dict], list[str]]:
    """The answer per note id, and every problem found (empty when usable)."""
    from datetime import date

    by_name = _topics_by_name(topics)
    for topic in list(by_name.values()):
        by_name.setdefault(_clean_name(topic["name"]), topic)
    problems: list[str] = []
    answers = data.get("notes") if isinstance(data, dict) else None
    if not isinstance(answers, list):
        return {}, ['The answer must be {"notes": [...]}.']
    wanted = {note["id"] for note in notes}
    seen: dict[int, dict] = {}
    for entry in answers:
        if not isinstance(entry, dict) or entry.get("id") not in wanted:
            problems.append(f"Unknown note id {entry.get('id') if isinstance(entry, dict) else entry!r}.")
            continue
        note_id = entry["id"]
        if note_id in seen:
            problems.append(f"Note {note_id} appears twice.")
            continue
        area = entry.get("area")
        topic_name = entry.get("topic")
        rule = entry.get("rule")
        confidence = entry.get("confidence")
        unsure = rule == "R6" or confidence == "low" or not topic_name
        if rule not in RULES:
            problems.append(f"Note {note_id}: rule must be one of R1-R6.")
        if confidence not in CONFIDENCE:
            problems.append(f"Note {note_id}: confidence must be high, medium or low.")
        topic = (by_name.get(str(topic_name).strip().lower()) or by_name.get(_clean_name(topic_name))) if topic_name else None
        if topic_name and topic is None:
            problems.append(f"Note {note_id}: topic \"{topic_name}\" doesn't exist; pick one from the list.")
        elif topic is not None and area and topic.get("bot_key") != area:
            problems.append(f"Note {note_id}: topic \"{topic['name']}\" belongs to area {topic.get('bot_key')}, not {area}.")
        choices = []
        for name in entry.get("choices") or []:
            choice = by_name.get(str(name).strip().lower()) or by_name.get(_clean_name(name))
            if choice is None:
                problems.append(f"Note {note_id}: choice \"{name}\" doesn't exist.")
            elif choice["id"] not in choices:
                choices.append(choice["id"])
        if unsure and not choices and topic is None:
            problems.append(f"Note {note_id}: when unsure, give the two likeliest topics in \"choices\".")
        if entry.get("priority") not in PRIORITIES:
            problems.append(f"Note {note_id}: priority must be High, Medium or Low.")
        tasks = []
        for task in entry.get("tasks") or []:
            if not isinstance(task, dict) or not str(task.get("task") or "").strip():
                problems.append(f"Note {note_id}: every task needs its text.")
                continue
            day = task.get("date")
            if day:
                try:
                    date.fromisoformat(str(day))
                except ValueError:
                    problems.append(f"Note {note_id}: \"{day}\" is not a real date (YYYY-MM-DD).")
                    continue
            clock = task.get("time")
            if clock and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(clock)):
                problems.append(f"Note {note_id}: \"{clock}\" is not a time (HH:MM).")
                continue
            intent = task.get("intent") or "commitment"
            if intent not in INTENTS:
                problems.append(f"Note {note_id}: a task's intent must be commitment, tentative or someday.")
                continue
            tasks.append({"task": str(task["task"]).strip(), "when": task.get("when") or None,
                          "date": day or None, "time": clock or None, "intent": intent})
        if unsure and topic is not None:
            choices = [topic["id"]] + [choice for choice in choices if choice != topic["id"]]
            topic = None
        memory_used, plan_update = _memory_fields(entry, pack, tasks)
        seen[note_id] = {
            "id": note_id,
            "topic": topic["id"] if topic is not None else None,
            "bot": topic.get("bot_key") if topic is not None else None,
            "rule": rule if rule in RULES else "R6",
            "confidence": confidence if confidence in CONFIDENCE else "low",
            "choices": choices[:2],
            "title": _title(entry.get("title") or ""),
            "priority": entry.get("priority") if entry.get("priority") in PRIORITIES else "Medium",
            "tags": [str(tag)[:30] for tag in (entry.get("tags") or [])][:6],
            "reason": str(entry.get("reason") or "").strip()[:300] or None,
            "tasks": tasks,
            "transcript": (str(entry.get("transcript")).strip() or None) if entry.get("transcript") else None,
            "summary": (str(entry.get("summary")).strip()[:600] or None) if entry.get("summary") else None,
            "action": (str(entry.get("action")).strip()[:60] or None) if entry.get("action") else None,
            "facts": [str(fact).strip()[:160] for fact in (entry.get("facts") or []) if str(fact).strip()][:2]
            if isinstance(entry.get("facts"), list) else [],
            "memory_used": memory_used,
            "plan_update": plan_update,
            "filed_by": "ai",
        }
    for note_id in wanted - set(seen):
        problems.append(f"Note {note_id} is missing from the answer.")
    return seen, problems


# --- running a batch ----------------------------------------------------------------------


def _is_secret(note: dict) -> bool:
    from app.sensitive import looks_secret

    return any(looks_secret(note.get(field)) for field in ("text", "context", "source_title"))


def _masked(note: dict) -> dict:
    from app.sensitive import mask_secrets

    return {**note, **{field: mask_secrets(note.get(field)) for field in ("text", "context", "source_title") if note.get(field)}}


def file_batch(notes: list[dict], topics: list[dict], *, compact: bool = False) -> tuple[list[dict], str]:
    """File these notes: one call (plus one repair), else the offline matcher.
    Returns each note's filing and the run's mode."""
    if not notes:
        return [], "empty_inbox"
    if not llm.is_configured():
        # Secret notes are filed from a masked copy here too, so the saved title
        # never holds the password (with AI off or no key).
        return [offline_file(_masked(note) if _is_secret(note) else note, topics) for note in notes], "fallback_no_api_call"
    # A note that looks like it holds a secret never reaches the AI (change 016):
    # the offline matcher files it from a masked copy.
    secret = [note for note in notes if _is_secret(note)]
    if secret:
        rest, mode = file_batch([note for note in notes if not _is_secret(note)], topics, compact=compact) \
            if len(secret) < len(notes) else ([], "fallback_no_api_call")
        by_id = {entry["id"]: entry for entry in rest}
        for note in secret:
            by_id[note["id"]] = offline_file(_masked(note), topics)
        return [by_id[note["id"]] for note in notes], mode
    pack = None
    if memory_on() and not compact:
        try:
            pack = memory_pack(notes, topics)
        except Exception:
            logger.exception("Memory pack failed; filing goes on without it")
    prompt = build_prompt(notes, topics, compact=compact, pack=pack)
    checked: dict[int, dict] = {}

    def validate(data: dict) -> Optional[str]:
        answers, problems = check_answer(data, notes, topics, pack=pack)
        if problems:
            return " ".join(problems[:6])
        checked.clear()
        checked.update(answers)
        return None

    try:
        llm.complete_json("filing", prompt, validate=validate, repair=True, max_prompt_tokens=PROMPT_LIMIT_TOKENS)
    except Exception:
        logger.exception("Filing call failed; using the offline matcher")
        return [offline_file(note, topics) for note in notes], "fallback_after_api_error"
    filed = [checked.get(note["id"]) or offline_file(note, topics) for note in notes]
    return filed, llm.provider()


def to_analysis(filed: list[dict], topics: list[dict], mode: str) -> tuple[dict, dict]:
    """The AnalysisResult the save path expects, and filing's own details."""
    names = {topic["id"]: topic["name"] for topic in topics}
    buckets: dict[str, list[dict]] = defaultdict(list)
    todos, priority_view = [], {"High": [], "Medium": [], "Low": []}
    meta: dict[int, dict] = {}
    task_dates: dict = {}
    ideas: dict[int, list] = defaultdict(list)
    facts: dict[int, list] = {}
    plan_updates: dict[int, dict] = {}
    for entry in filed:
        pending = entry.get("topic") is None
        bucket = database.PENDING_BUCKET if pending else names[entry["topic"]]
        reason = entry.get("reason") or RULE_SHORT.get(entry.get("rule"), "")
        buckets[bucket].append({
            "id": entry["id"], "title": entry["title"], "priority": entry["priority"],
            "tags": entry.get("tags") or [], "rationale": reason,
        })
        priority_view[entry["priority"]].append({"id": entry["id"], "title": entry["title"]})
        for task in entry.get("tasks") or []:
            if task.get("intent") in ("tentative", "someday"):
                # Not a commitment: kept as an idea, asked about or kept for someday (014a).
                ideas[entry["id"]].append({"text": task["task"], "when": task.get("when"), "intent": task["intent"]})
                continue
            when = task.get("when")
            if task.get("time") and when and task["time"] not in when:
                when = f"{when} at {task['time']}"
            todos.append({"task": task["task"], "priority": entry["priority"], "source_note_ids": [entry["id"]], "when": when})
            if task.get("date"):
                task_dates[(entry["id"], database._normalize_task_text(task["task"]))] = task["date"]
        meta[entry["id"]] = {
            "rule": entry.get("rule"), "confidence": entry.get("confidence"),
            "choices": entry.get("choices") or [], "filed_by": entry.get("filed_by"),
            "summary": entry.get("summary"), "action": entry.get("action"),
            "cleaned_transcript": entry.get("transcript"),
            "memory_used": entry.get("memory_used") or [],
        }
        if entry.get("facts"):
            facts[entry["id"]] = entry["facts"]
        if entry.get("plan_update"):
            plan_updates[entry["id"]] = entry["plan_update"]
    result = {
        "buckets": [{"name": name, "notes": notes} for name, notes in buckets.items()],
        "todos": todos,
        "priority_view": priority_view,
        "mode": mode,
    }
    return result, {"notes": meta, "task_dates": task_dates, "ideas": dict(ideas), "facts": facts,
                    "plan_updates": plan_updates}


def _file_and_save(notes: list[dict], topics: list[dict], *, compact: bool = False) -> tuple[list[dict], str, dict]:
    """One analysis run: file the notes and save them. A failure is recorded
    as a failed run and never touches the last good one."""
    run_id = database.start_analysis_run()
    try:
        filed, mode = file_batch(notes, topics, compact=compact)
        result, meta = to_analysis(filed, topics, mode)
        persisted = database.complete_analysis_run(run_id, result, merge_single=True, filing=meta)
    except Exception:
        database.fail_analysis_run(run_id)
        raise
    return filed, mode, persisted


def _save(filed: list[dict], topics: list[dict], mode: str) -> dict:
    run_id = database.start_analysis_run()
    try:
        result, meta = to_analysis(filed, topics, mode)
        return database.complete_analysis_run(run_id, result, merge_single=True, filing=meta)
    except Exception:
        database.fail_analysis_run(run_id)
        raise


# --- batching: notes saved while a call runs share the next one (decision G) ----------------

_guard = threading.Lock()
_owner_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)
_waiting: dict[int, list[int]] = defaultdict(list)
_results: dict[tuple[int, int], dict] = {}


def file_items(item_ids: list[int]) -> dict:
    """File these notes (after saving). If a call is already running for you,
    they wait and go together in the next one, up to 5 per call."""
    owner = database.require_owner_id()
    with _guard:
        for item_id in item_ids:
            if item_id not in _waiting[owner]:
                _waiting[owner].append(item_id)
    with _owner_locks[owner]:
        with _guard:
            if not any(item_id in _waiting[owner] for item_id in item_ids):
                # An earlier batch filed them while we waited.
                done = [_results.pop((owner, item_id), None) for item_id in item_ids]
                if all(done):
                    return done[-1]
                for item_id in item_ids:  # that batch failed: file them now
                    _waiting[owner].insert(0, item_id)
            batch = [item_id for item_id in item_ids if item_id in _waiting[owner]]
            batch += [item_id for item_id in _waiting[owner] if item_id not in batch]
            batch = batch[:MAX_BATCH]
            for item_id in batch:
                _waiting[owner].remove(item_id)
        notes = [note for note in (database.get_note_from_db(item_id) for item_id in batch) if note]
        topics = database.list_topics_from_db()
        _, _, persisted = _file_and_save(notes, topics)
        with _guard:
            for item_id in batch:
                if item_id not in item_ids:
                    _results[(owner, item_id)] = persisted
        return persisted


# --- Re-sort everything (only when you ask) --------------------------------------------------


def resort_plan() -> dict:
    notes = database.list_resort_candidates()
    calls = math.ceil(len(notes) / RESORT_BATCH) if llm.is_configured() else 0
    return {"notes": len(notes), "calls": calls, "per_call": RESORT_BATCH, "ai": llm.is_configured()}


def resort_all() -> dict:
    """Re-file every note you didn't file yourself, 25 per call. Notes in the
    old catch-all are re-sorted into real topics, or wait in Needs you; the
    catch-all is removed once empty."""
    ids = database.list_resort_candidates()
    topics = database.list_topics_from_db()
    persisted = None
    calls = 0
    waiting = 0
    if not ids:
        _, _, persisted = _file_and_save([], topics)  # an empty, valid analysis
    for start in range(0, len(ids), RESORT_BATCH):
        notes = [note for note in (database.get_note_from_db(i) for i in ids[start:start + RESORT_BATCH]) if note]
        filed, mode, persisted = _file_and_save(notes, topics, compact=True)
        calls += 1 if mode not in ("fallback_no_api_call", "empty_inbox") else 0
        waiting += sum(1 for entry in filed if entry.get("topic") is None)
    retired = database.retire_catch_all_if_empty()
    return {"analysis": persisted, "notes": len(ids), "calls": calls, "waiting": waiting, "retired_catch_all": retired}


# --- a new topic: re-check only the notes code finds as likely fits ---------------------------


def recheck_for_topic(topic_id: int) -> dict:
    """After you create a topic: the notes whose words fit it (at most 25, so
    0-1 call) are filed again, and those that now belong in it move there.
    Returns the moves, so "Undo" can put them back."""
    topics = database.list_topics_from_db()
    topic = next((t for t in topics if t["id"] == topic_id), None)
    if topic is None:
        raise LookupError("Topic not found.")
    already = database.notes_in_topic(topic_id)
    candidates = []
    for item_id in database.list_resort_candidates():
        if item_id in already:
            continue
        note = database.get_note_from_db(item_id)
        if note and _topic_fit(f"{own_words(note)} {note.get('text') or ''} {note.get('source_title') or ''}", topic):
            candidates.append(note)
        if len(candidates) >= RESORT_BATCH:
            break
    if not candidates:
        return {"topic": {"id": topic["id"], "name": topic["name"]}, "moved": [], "calls": 0}
    filed, mode = file_batch(candidates, topics, compact=True)
    calls = 1 if mode not in ("fallback_no_api_call", "empty_inbox") else 0
    moving = [entry for entry in filed if entry.get("topic") == topic_id]
    before = database.topic_assignments([entry["id"] for entry in moving])
    if moving:
        _save(moving, topics, mode)
    titles = {note["id"]: _title(note.get("source_title") or own_words(note) or note.get("text")) for note in candidates}
    return {
        "topic": {"id": topic["id"], "name": topic["name"]},
        "moved": [{"item_id": e["id"], "title": titles.get(e["id"]), "topic_id": before.get(e["id"])} for e in moving],
        "calls": calls,
    }
