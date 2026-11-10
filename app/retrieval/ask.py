"""Grounded answers with source citations: Ask me (change 019, "Ask me v2").

Routing is code: the lens if an area is picked, else the areas of the
best-matching notes. Evidence: up to 5 passages from search (your notes on
sources included), the confirmed memory facts that share words with the
question (each with the notes it came from), and your tasks for the period the
question names ("this week", "Saturday", "12 Nov"; worked out by code). One
AI call; none when nothing matches. Every claim must cite the evidence; code
checks every citation, one repair call names what failed, then the quoted
answer from the notes themselves. "How I answered" says which areas were
asked, how many remembered facts were used, and which notes were read.
Suggested actions ("Confirm Sat 14 Nov for Call mom?") run only when tapped.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Optional

from app.sensitive import mask_secrets
from app import llm
from app.retrieval.search import RankedPassage, search_passages

logger = logging.getLogger(__name__)

# Ask me v2 (019): no evidence, no AI call and no guess.
INSUFFICIENT = "I couldn't find that in your notes, so I won't guess."
_FACT_LIMIT = 5
_TASK_LIMIT = 10
_ACTION_LIMIT = 3
_STOP = frozenset(
    "the and for with that this from your you are was have has had not but all any can her his its our out "
    "she they them then than too very will just about into over under when what which who why how also some "
    "more most other such only own same so to of in on at by an a is it be as or if do my me we i did does "
    "there here".split()
)
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_MONTHS = {name: number for number, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}

# Bound evidence packed into the LLM prompt (retrieved passages only).
_MAX_EVIDENCE_PASSAGES = 5
_MAX_PASSAGE_CHARS = 400
_MAX_EVIDENCE_TOTAL_CHARS = 6000
_MAX_ANSWER_CHARS = 2000


def _citation_id(item_id: int, index: int) -> str:
    return f"item-{item_id}-{index}"


def _build_citations(ranked: list[RankedPassage]) -> list[dict]:
    citations: list[dict] = []
    seen: set[tuple[int, str]] = set()
    for idx, row in enumerate(ranked, start=1):
        key = (row.passage.item_id, row.passage.passage[:80])
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "id": _citation_id(row.passage.item_id, idx),
                "item_id": row.passage.item_id,
                "item_type": row.passage.item_type,
                # A secret is never shown, and never sent to the AI (change 016).
                "title": mask_secrets(row.passage.title),
                "excerpt": mask_secrets(row.passage.passage[:320]),
                "source_kind": row.passage.source_kind,
                "preview_url": row.passage.preview_url,
                "score": round(row.score, 4),
            }
        )
    return citations


def _extractive_answer(ranked: list[RankedPassage]) -> str:
    lead = ranked[0].passage
    supporting = ranked[1:3]
    parts = [
        f"Based on your inbox item “{lead.title}” ({lead.source_kind}): "
        f"{lead.passage[:280]}{'…' if len(lead.passage) > 280 else ''}"
    ]
    for row in supporting:
        parts.append(
            f"Also related: “{row.passage.title}” — {row.passage.passage[:160]}"
            f"{'…' if len(row.passage.passage) > 160 else ''}"
        )
    return " ".join(parts)


def _insufficient_payload(question: str) -> dict:
    return {
        "question": question,
        "answer": INSUFFICIENT,
        "confidence": "insufficient",
        "citations": [],
        "answer_kind": "model_generated",
        "mode": "extractive_fallback",
    }


def _extractive_payload(
    question: str,
    ranked: list[RankedPassage],
    citations: list[dict],
) -> dict:
    top = ranked[0]
    confidence = "high" if top.score >= 0.45 else "medium"
    return {
        "question": question,
        "answer": _extractive_answer(ranked),
        "confidence": confidence,
        "citations": citations,
        "answer_kind": "grounded_summary",
        "mode": "extractive_fallback",
    }


def _pack_evidence(citations: list[dict]) -> list[dict]:
    packed: list[dict] = []
    total = 0
    for cite in citations[:_MAX_EVIDENCE_PASSAGES]:
        excerpt = (cite.get("excerpt") or "")[:_MAX_PASSAGE_CHARS]
        if total + len(excerpt) > _MAX_EVIDENCE_TOTAL_CHARS:
            remaining = _MAX_EVIDENCE_TOTAL_CHARS - total
            if remaining <= 0:
                break
            excerpt = excerpt[:remaining]
        packed.append(
            {
                "citation_id": cite["id"],
                "item_id": cite["item_id"],
                "title": (cite.get("title") or "")[:120],
                "source_kind": cite.get("source_kind") or "",
                "excerpt": excerpt,
            }
        )
        total += len(excerpt)
    return packed


def _validate_llm_payload(
    parsed: dict,
    *,
    allowed_citation_ids: set[str],
    citations_by_id: dict[str, dict],
) -> Optional[dict]:
    """Return normalized answer fields or None if the model output is unusable."""
    if not isinstance(parsed, dict):
        return None

    answer = parsed.get("answer")
    if not isinstance(answer, str):
        return None
    answer = answer.strip()
    if not answer or len(answer) > _MAX_ANSWER_CHARS:
        return None

    confidence = parsed.get("confidence")
    if confidence not in {"high", "medium", "insufficient"}:
        return None

    raw_ids = parsed.get("citation_ids")
    if raw_ids is None:
        raw_ids = []
    if not isinstance(raw_ids, list):
        return None

    selected: list[dict] = []
    seen: set[str] = set()
    for cid in raw_ids:
        if not isinstance(cid, str) or cid not in allowed_citation_ids:
            return None
        if cid in seen:
            continue
        seen.add(cid)
        selected.append(citations_by_id[cid])

    if confidence == "insufficient":
        # Model may still list ids; prefer empty citations for this path.
        return {
            "answer": answer if answer else INSUFFICIENT,
            "confidence": "insufficient",
            "citations": [],
        }

    if not selected:
        return None

    return {
        "answer": answer,
        "confidence": confidence,
        "citations": selected,
    }


def _content_words(text: Optional[str]) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(word) > 2 and word not in _STOP}


def _day_label(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b}"


def question_period(question: str, today: date) -> Optional[dict]:
    """The days a question asks about, worked out by code: today, tomorrow,
    yesterday, this/next/last week, the weekend, a weekday, this/next month,
    or a date ("2026-11-14", "14 Nov", "Nov 14"). None when it names none."""
    lower = (question or "").lower()

    def span(start: date, end: date, label: str) -> dict:
        when = _day_label(start) if start == end else f"{_day_label(start)} – {_day_label(end)}"
        return {"start": start.isoformat(), "end": end.isoformat(), "label": f"{label} ({when})"}

    monday = today - timedelta(days=today.weekday())
    if re.search(r"\btoday\b|\btonight\b", lower):
        return span(today, today, "today")
    if re.search(r"\btomorrow\b", lower):
        return span(today + timedelta(days=1), today + timedelta(days=1), "tomorrow")
    if re.search(r"\byesterday\b", lower):
        return span(today - timedelta(days=1), today - timedelta(days=1), "yesterday")
    if re.search(r"\bnext week\b", lower):
        return span(monday + timedelta(days=7), monday + timedelta(days=13), "next week")
    if re.search(r"\blast week\b", lower):
        return span(monday - timedelta(days=7), monday - timedelta(days=1), "last week")
    if "weekend" in lower:
        saturday = today + timedelta(days=(5 - today.weekday()) % 7) if today.weekday() != 6 else today - timedelta(days=1)
        return span(max(saturday, today), saturday + timedelta(days=1), "this weekend")
    if re.search(r"\bthis week\b|\bthe week\b", lower):
        return span(monday, monday + timedelta(days=6), "this week")
    if re.search(r"\bnext month\b", lower):
        first = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return span(first, last, "next month")
    if re.search(r"\bthis month\b", lower):
        last = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return span(today.replace(day=1), last, "this month")
    iso = re.search(r"\b(20\d\d)-(\d\d)-(\d\d)\b", lower)
    named = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b", lower) \
        or re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b", lower)
    try:
        if iso:
            day = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
            return span(day, day, "that day")
        if named:
            first, second = named.group(1), named.group(2)
            number, month = (first, second) if first.isdigit() else (second, first)
            day = date(today.year, _MONTHS[month[:3]], int(number))
            if day < today - timedelta(days=180):
                day = day.replace(year=today.year + 1)
            return span(day, day, "that day")
    except ValueError:
        return None
    for index, name in enumerate(_WEEKDAYS):
        if re.search(rf"\b{name}\b", lower):
            ahead = (index - today.weekday()) % 7
            if re.search(rf"\blast {name}\b", lower):
                ahead = ahead - 7 if ahead else -7
            day = today + timedelta(days=ahead)
            return span(day, day, name.capitalize())
    return None


def _fact_evidence(question: str, bot: Optional[str]) -> list[dict]:
    """Confirmed facts that share words with the question (the lens's own when picked)."""
    from app.database import list_memory

    words = _content_words(question)
    if not words:
        return []
    facts = list_memory(bot=bot, statuses=("confirmed",)) if bot else list_memory(statuses=("confirmed",))
    scored = [(len(_content_words(fact["text"]) & words), fact) for fact in facts]
    scored = sorted((row for row in scored if row[0]), key=lambda row: (-row[0], -row[1]["id"]))
    return [{"id": f"m{fact['id']}", "fact_id": fact["id"], "text": fact["text"],
             "source_item_ids": fact["source_item_ids"], "bot_key": fact["bot_key"]}
            for _, fact in scored[:_FACT_LIMIT]]


def _task_evidence(period: Optional[dict], bot: Optional[str]) -> list[dict]:
    """Your tasks on the days asked about (open or done; dropped ones left out)."""
    if not period:
        return []
    from app.database import list_tasks_from_db

    found = []
    for task in list_tasks_from_db("all", bot=bot):
        day = task.get("due_on") or task.get("suggested_due_on")
        if task["status"] == "dismissed" or not day or not (period["start"] <= day <= period["end"]):
            continue
        found.append({
            "id": f"t{task['id']}", "task_id": task["id"], "text": mask_secrets(task["text"]), "day": day,
            "time": task.get("due_time") or task.get("suggested_due_time"),
            "confirmed": bool(task.get("due_on")), "status": task["status"],
            "source_item_ids": task.get("source_item_ids") or [],
        })
    found.sort(key=lambda task: (task["day"], task["time"] or "99:99", task["task_id"]))
    return found[:_TASK_LIMIT]


def _areas(bot: Optional[str], citations: list[dict]) -> list[str]:
    if bot:
        return [bot]
    from app.database import bots_for_items

    mapping = bots_for_items([cite["item_id"] for cite in citations])
    areas: list[str] = []
    for cite in citations:
        key = mapping.get(cite["item_id"])
        if key and key not in areas:
            areas.append(key)
    return areas


def _suggested_actions(tasks: list[dict]) -> list[dict]:
    """Only code suggests, and nothing runs until you tap it."""
    actions = []
    for task in tasks:
        if task["status"] == "open" and not task["confirmed"]:
            day = _day_label(date.fromisoformat(task["day"]))
            actions.append({"kind": "confirm_date", "task_id": task["task_id"], "due_on": task["day"],
                            "due_time": task["time"], "label": f"Confirm {day} for “{task['text'][:60]}”?"})
    return actions[:_ACTION_LIMIT]


def _task_line(task: dict) -> str:
    when = _day_label(date.fromisoformat(task["day"])) + (f" at {task['time']}" if task["time"] else "")
    extra = " (done)" if task["status"] == "completed" else ("" if task["confirmed"] else " (date not confirmed)")
    return f"{task['text']}, {when}{extra}"


def _check_answer(parsed: dict, allowed: set[str]) -> tuple[Optional[str], dict]:
    """Code's checks on the model's answer: the reason it can't be used (for
    the repair call), or the usable fields."""
    if not isinstance(parsed, dict):
        return "The answer must be one JSON object.", {}
    answer = parsed.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return "\"answer\" must be a non-empty string.", {}
    if len(answer) > _MAX_ANSWER_CHARS:
        return f"\"answer\" must be under {_MAX_ANSWER_CHARS} characters.", {}
    confidence = parsed.get("confidence")
    if confidence not in {"high", "medium", "insufficient"}:
        return "\"confidence\" must be high, medium or insufficient.", {}
    ids = parsed.get("citation_ids") if parsed.get("citation_ids") is not None else []
    if not isinstance(ids, list):
        return "\"citation_ids\" must be a list.", {}
    unknown = [str(cid) for cid in ids if not isinstance(cid, str) or cid not in allowed]
    if unknown:
        return f"These citation ids are not in the evidence: {', '.join(unknown[:5])}. Use only the evidence's ids.", {}
    claims = []
    raw_claims = parsed.get("claims") or []
    if not isinstance(raw_claims, list):
        return "\"claims\" must be a list.", {}
    for claim in raw_claims:
        if not isinstance(claim, dict) or not str(claim.get("claim") or "").strip():
            return "Every claim needs its \"claim\" text.", {}
        cited = [cid for cid in claim.get("citation_ids") or [] if isinstance(cid, str) and cid in allowed]
        if not cited:
            return f"The claim \"{str(claim['claim'])[:60]}\" cites nothing from the evidence; every claim must.", {}
        claims.append({"claim": str(claim["claim"]).strip()[:300], "citation_ids": cited})
    if confidence == "insufficient":
        return None, {"answer": answer.strip(), "confidence": "insufficient", "ids": [], "claims": []}
    every = list(dict.fromkeys(list(ids) + [cid for claim in claims for cid in claim["citation_ids"]]))
    if not every:
        return "A high or medium answer must cite at least one evidence id.", {}
    return None, {"answer": answer.strip(), "confidence": confidence, "ids": every, "claims": claims}


def _synthesize_from_evidence(
    question: str,
    citations: list[dict],
    facts: Optional[list[dict]] = None,
    tasks: Optional[list[dict]] = None,
    period: Optional[dict] = None,
    counter: Optional[list] = None,
) -> Optional[dict]:
    """Ask the model, with the evidence only. Returns checked fields or None."""
    from app.attention.dates import today_in_configured_tz

    facts, tasks = facts or [], tasks or []
    evidence: dict = {}
    passages = _pack_evidence(citations)
    if passages:
        evidence["passages"] = passages
    if facts:
        evidence["facts"] = [{"citation_id": fact["id"], "fact": fact["text"]} for fact in facts]
    if tasks:
        evidence["tasks"] = [{"citation_id": task["id"], "task": task["text"], "day": task["day"],
                              "time": task["time"], "date_confirmed": task["confirmed"], "status": task["status"]}
                             for task in tasks]
    if not evidence:
        return None
    allowed = {c["id"] for c in citations} | {f["id"] for f in facts} | {t["id"] for t in tasks}
    today = today_in_configured_tz()
    period_line = f"The question is about {period['label']}.\n" if period else ""
    prompt = f"""You are Ask me for a personal Life Inbox.

Answer the user's question using ONLY the evidence: passages from their notes, facts Life Inbox
remembers about them, and their tasks on the days asked about. No outside knowledge. Never invent
facts, people, dates or citations. If the evidence doesn't answer it, say so and use "insufficient".
Today is {today:%A %d %B %Y}. {period_line}
Return ONLY valid JSON in exactly this shape:
{{
  "answer": "short grounded answer in plain language",
  "confidence": "high",
  "citation_ids": ["item-1-1", "t7"],
  "claims": [{{"claim": "one statement from the answer", "citation_ids": ["t7"]}}]
}}

Rules:
1. confidence is one of: high, medium, insufficient.
2. citation_ids come only from the evidence's citation_id values.
3. Every statement of fact in the answer is a claim with at least one citation_id.
4. A task with "date_confirmed": false has a suggested day, not a set one: say so.
5. Keep the answer concise and grounded in the evidence.

Question:
{question.strip()[:500]}

Evidence (JSON):
{json.dumps(evidence, ensure_ascii=False)}
"""
    usable: dict = {}

    def check(parsed: dict) -> Optional[str]:
        if counter is not None:
            counter.append(1)
        problem, fields = _check_answer(parsed, allowed)
        if problem:
            return problem
        usable.clear()
        usable.update(fields)
        return None

    try:
        llm.complete_json("ask", prompt, validate=check, repair=True)
    except llm.InvalidOutput:
        return None
    by_id = {c["id"]: c for c in citations}
    usable["citations"] = [by_id[cid] for cid in usable["ids"] if cid in by_id]
    usable["facts"] = [fact for fact in facts if fact["id"] in usable["ids"]]
    usable["tasks"] = [task for task in tasks if task["id"] in usable["ids"]]
    return usable


def _old_synthesize_unused(
    question: str,
    citations: list[dict],
) -> Optional[dict]:
    """Ask the model, with retrieved evidence only. Returns validated fields or None."""
    evidence = _pack_evidence(citations)
    if not evidence:
        return None

    allowed_ids = {c["id"] for c in citations}
    citations_by_id = {c["id"]: c for c in citations}

    prompt = f"""You are Ask My Inbox for a personal Life Inbox.

Answer the user's question using ONLY the supplied evidence passages from their inbox.
Do not use outside knowledge. Do not invent facts, people, dates, or citations.
If the evidence is insufficient to answer, say so clearly and set confidence to "insufficient".

Return ONLY valid JSON in exactly this shape:
{{
  "answer": "short grounded answer in plain language",
  "confidence": "high",
  "citation_ids": ["item-1-1"]
}}

Rules:
1. confidence must be one of: high, medium, insufficient.
2. citation_ids must be a subset of the citation_id values from the evidence list.
3. For factual answers (confidence high or medium), include at least one citation_id that supports the answer.
4. Never invent citation_ids that are not in the evidence.
5. Keep the answer concise and grounded in the excerpts.

Question:
{question.strip()[:500]}

Evidence (JSON):
{json.dumps(evidence, ensure_ascii=False)}
"""

    usable: dict = {}

    def check(parsed: dict) -> Optional[str]:
        fields = _validate_llm_payload(
            parsed,
            allowed_citation_ids=allowed_ids,
            citations_by_id=citations_by_id,
        )
        if fields is None:
            return "The answer, confidence or citation ids were not usable."
        usable.clear()
        usable.update(fields)
        return None

    try:
        llm.complete_json("ask", prompt, validate=check)
    except llm.InvalidOutput:
        return None
    return dict(usable)


def _payload(question, answer, confidence, citations, kind, mode, *, facts=(), tasks=(), claims=(),
             actions=(), how=None) -> dict:
    return {
        "question": question, "answer": answer, "confidence": confidence, "citations": list(citations),
        "answer_kind": kind, "mode": mode, "facts": [
            {"id": fact["fact_id"], "text": fact["text"], "source_item_ids": fact["source_item_ids"]} for fact in facts],
        "tasks": [{key: task[key] for key in ("task_id", "text", "day", "time", "confirmed", "status", "source_item_ids")}
                  for task in tasks],
        "claims": list(claims), "suggested_actions": list(actions), "how": how,
    }


def build_grounded_answer(
    question: str,
    *,
    limit: int = 5,
    item_type: Optional[str] = None,
    bot: Optional[str] = None,
) -> dict:
    from app.attention.dates import today_in_configured_tz
    from app.database import item_ids_for_bot

    period = question_period(question, today_in_configured_tz())
    ranked = search_passages(
        question,
        limit=limit,
        item_type=item_type,
        min_score=0.15,
        item_ids=item_ids_for_bot(bot) if bot else None,
    )
    if ranked and ranked[0].score < 0.2 and ranked[0].keyword_score < 0.25:
        ranked = []  # too weak to count as evidence
    citations = _build_citations(ranked)
    facts = _fact_evidence(question, bot)
    tasks = _task_evidence(period, bot)
    actions = _suggested_actions(tasks)
    how = {
        "areas": _areas(bot, citations), "lens": bot, "notes_read": list(dict.fromkeys(c["item_id"] for c in citations)),
        "facts_considered": len(facts), "memory_used": 0, "tasks_read": len(tasks),
        "period": period["label"] if period else None, "ai_calls": 0,
    }
    if not citations and not facts and not tasks:
        return _payload(question, INSUFFICIENT, "insufficient", [], "model_generated", "extractive_fallback", how=how)

    if llm.is_configured():
        counter: list = []
        try:
            synthesized = _synthesize_from_evidence(question, citations, facts, tasks, period, counter=counter)
        except Exception:
            synthesized = None
            logger.exception("Ask me synthesis failed; using the quoted answer")
        how["ai_calls"] = max(1, len(counter))
        if synthesized is not None:
            how["memory_used"] = len(synthesized["facts"])
            if synthesized["confidence"] == "insufficient":
                return _payload(question, synthesized["answer"] or INSUFFICIENT, "insufficient", [], "model_generated",
                                "llm_grounded", actions=actions, how=how)
            return _payload(question, synthesized["answer"], synthesized["confidence"], synthesized["citations"],
                            "model_generated", "llm_grounded", facts=synthesized["facts"], tasks=synthesized["tasks"],
                            claims=synthesized["claims"], actions=actions, how=how)

    # The quoted answer: the notes' own words, your tasks for those days, and
    # what Life Inbox remembers, put together by code.
    parts, confidence = [], "medium"
    if ranked:
        parts.append(_extractive_answer(ranked))
        confidence = "high" if ranked[0].score >= 0.45 else "medium"
    if tasks:
        parts.append(f"For {period['label']}: " + "; ".join(_task_line(task) for task in tasks) + ".")
    if facts and not ranked:
        parts.append("Life Inbox remembers: " + "; ".join(fact["text"] for fact in facts))
    how["memory_used"] = len(facts) if facts and not ranked else 0
    return _payload(question, " ".join(parts), confidence, citations, "grounded_summary", "extractive_fallback",
                    facts=facts if facts and not ranked else [], tasks=tasks, actions=actions, how=how)
