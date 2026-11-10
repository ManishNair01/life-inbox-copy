"""The five life areas: every topic belongs to a bot, each bot has 3 default topics.

- Adds `topics.bot_key` (learn, money, health, people, fun; NULL means not in an
  area yet) and `topics.origin` (built_in, user, ai).
- Moves v1's nine built-in topics onto the new defaults. It renames them, so
  every note stays on its topic, and adds the missing defaults. "Personal /
  Reference" is kept with no bot until change 014 re-sorts its notes.
- Gives users' own topics a bot: a subtopic takes its parent's; a main topic is
  matched by keywords, or left without one for Captain to ask about (013).

The constants are copied here on purpose, so this migration never changes when
the app's settings do (the live versions are in app/bots.py).

Revision ID: 0018_five_life_areas
Revises: 0017_ai_call_log
"""

import json
from datetime import datetime, timezone
from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0018_five_life_areas"
down_revision: Optional[str] = "0017_ai_call_log"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None

# v1 built-in topic -> the new default it becomes (design §4.1 "Moving from v1").
RENAMES = {
    "Learning": "Study",
    "Work": "Work & career",
    "Money & Admin": "Bills & subscriptions",
    "Shopping & Errands": "Home & errands",
    "Health": "Medicines & doctors",
    "Travel": "Trips & places",
    "Ideas": "Skills & projects",
    "People": "Friends & partner",
}

# v1 built-in descriptions (migration 0015). A different text means the user
# edited it, and theirs is kept.
V1_DESCRIPTIONS = {
    "Work": "Job, meetings, colleagues, projects, interviews and career.",
    "Money & Admin": "Bills, taxes, insurance, banking, paperwork and subscriptions.",
    "Learning": "Things to read, watch, study or look into; courses and articles.",
    "Shopping & Errands": "Things to buy, pick up, order or get done around town.",
    "Health": "Doctors, medicines, fitness, diet, sleep and wellbeing.",
    "Travel": "Trips, bookings, flights, hotels and places to visit.",
    "Ideas": "Product, business and creative ideas worth keeping.",
    "People": "Friends and family: calls, follow-ups, birthdays and favours.",
}

# (name, description, bot) for the 15 defaults, from docs/research-life-categories.md §3.
DEFAULTS = (
    ("Study", "Courses, exams, assignments, study notes, and college life you take part in (admin, clubs, events).", "learn"),
    ("Work & career", "Job or internship tasks, meetings, interviews, applications, salary talks, colleagues, work travel.", "learn"),
    ("Skills & projects", "Self-directed learning, tutorials, tools to try, side projects, app and startup ideas.", "learn"),
    ("Bills & subscriptions", "Anything you pay or cancel on a schedule: rent, bills, EMIs, subscriptions, memberships, fees.", "money"),
    ("Bank, tax & documents", "Accounts, savings, salary received, investments, tax filing, insurance policies, IDs, warranties.", "money"),
    ("Home & errands", "Groceries, shopping, chores, repairs, appliances, vehicle, pets, household info.", "money"),
    ("Medicines & doctors", "Pills, doses, refills, appointments, tests, checkups, prescriptions.", "health"),
    ("Fitness & food", "Workouts, sports routines, steps, sleep, diet and nutrition goals.", "health"),
    ("Mind & mood", "Feelings, stress, therapy, meditation, journaling, faith or reflection practice.", "health"),
    ("Family", "Parents, siblings, spouse, kids: their needs, school, family plans.", "people"),
    ("Friends & partner", "Friends, boyfriend/girlfriend, catch-ups, people to call or message.", "people"),
    ("Occasions & gifts", "Birthdays, anniversaries, weddings, dates, parties, gatherings, gifts, invites.", "people"),
    ("Watch, read & listen", "Your media queue, plus quotes and highlights from it.", "fun"),
    ("Cooking & hobbies", "Recipes to try, cooking ideas, games, crafts, creative pursuits.", "fun"),
    ("Trips & places", "Holidays, itineraries, bookings, trip visas, packing, places to visit.", "fun"),
)
DEFAULT_BOT = {name: bot for name, _description, bot in DEFAULTS}

# Keyword rules (first match wins) for giving a user's main topic a bot.
RULES = (
    ("Work & career", ("team", "meeting", "architecture", "recruiter", "finance", "interview", "document")),
    ("Bills & subscriptions", ("bill", "domain", "reimbursement")),
    ("Bank, tax & documents", ("tax", "insurance", "ca ", "passport")),
    ("Mind & mood", ("therapy", "therapist", "stress", "meditat")),
    ("Watch, read & listen", ("movie", "podcast", "song")),
    ("Study", ("read", "watch", "lecture", "article", "learn", "vector database", "prompt injection")),
    ("Home & errands", ("buy", "groceries", "pick up", "order", "dry cleaning")),
    ("Medicines & doctors", (
        "dentist", "health", "doctor", "medicine", "medication", "pill", "tablet", "dose",
        "dosage", "prescription", "pharmacy", "vitamin", "hospital", "clinic",
    )),
    ("Fitness & food", ("workout", "fitness", "gym", "diet")),
    ("Cooking & hobbies", ("recipe", "cook")),
    ("Trips & places", ("trip", "travel", "hotel", "jaipur", "flight", "visa")),
    ("Skills & projects", ("idea", "build", "app", "startup", "product")),
    ("Occasions & gifts", ("birthday",)),
    ("Family", ("papa", "mom", "family")),
    ("Friends & partner", ("call", "ask", "rohan", "friend")),
)

CATCH_ALL = "Personal / Reference"
AI_CREATED_DESCRIPTION = "Created from AI organization"


def _bot_for_text(text: str) -> Optional[str]:
    lowered = (text or "").lower()
    for name, markers in RULES:
        if any(marker in lowered for marker in markers):
            return DEFAULT_BOT[name]
    return None


def _owner_clause(owner, column="owner_user_id"):
    if owner is None:
        return f"{column} IS NULL", {}
    return f"{column} = :owner", {"owner": owner}


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("topics")}
    missing = [name for name in ("bot_key", "origin") if name not in columns]
    if missing:
        with op.batch_alter_table("topics") as batch:
            if "bot_key" in missing:
                batch.add_column(sa.Column("bot_key", sa.Text(), nullable=True))
            if "origin" in missing:
                batch.add_column(
                    sa.Column("origin", sa.Text(), nullable=False, server_default="user")
                )
    now = datetime.now(timezone.utc).isoformat()
    owners = [row[0] for row in bind.execute(sa.text("SELECT DISTINCT owner_user_id FROM topics"))]
    for owner in owners:
        _move_owner_topics(bind, owner, now)


def _load_topics(bind, owner) -> list[dict]:
    clause, params = _owner_clause(owner)
    rows = bind.execute(
        sa.text(f"SELECT id, name, description, parent_topic_id FROM topics WHERE {clause}"),
        params,
    ).mappings()
    return [dict(row) for row in rows]


def _move_owner_topics(bind, owner, now: str) -> None:
    topics = _load_topics(bind, owner)
    if not topics:
        return  # the app creates the new defaults on first use
    by_name = {topic["name"].strip().lower(): topic for topic in topics}
    built_in_ids: set[int] = set()

    # 1. Rename the v1 built-ins (or merge them into a same-named topic).
    for old, new in RENAMES.items():
        source = by_name.get(old.lower())
        if source is None:
            continue
        current = (source["description"] or "").strip()
        new_description = next(d for n, d, _b in DEFAULTS if n == new)
        description = new_description if current in ("", V1_DESCRIPTIONS[old]) else source["description"]
        target = by_name.get(new.lower())
        if target is None or target["id"] == source["id"]:
            bind.execute(
                sa.text(
                    "UPDATE topics SET name = :name, description = :description, bot_key = :bot, "
                    "origin = 'built_in', updated_at = :now WHERE id = :id"
                ),
                {"name": new, "description": description, "bot": DEFAULT_BOT[new], "now": now, "id": source["id"]},
            )
            kept = source
        else:
            _merge_topic(bind, source["id"], target["id"])
            bind.execute(
                sa.text(
                    "UPDATE topics SET name = :name, bot_key = :bot, origin = 'built_in', "
                    "parent_topic_id = NULL, updated_at = :now, "
                    "description = CASE WHEN description IS NULL OR TRIM(description) = '' "
                    "THEN :description ELSE description END WHERE id = :id"
                ),
                {"name": new, "bot": DEFAULT_BOT[new], "now": now, "description": description, "id": target["id"]},
            )
            kept = target
        by_name.pop(old.lower(), None)
        kept["name"] = new
        by_name[new.lower()] = kept
        built_in_ids.add(kept["id"])
        _rename_category(bind, owner, old, new)

    # 2. Add the defaults this user doesn't have; adopt same-named topics.
    for name, description, bot in DEFAULTS:
        existing = by_name.get(name.lower())
        if existing is not None:
            if existing["id"] not in built_in_ids:
                bind.execute(
                    sa.text(
                        "UPDATE topics SET name = :name, bot_key = :bot, origin = 'built_in', "
                        "parent_topic_id = NULL, updated_at = :now, "
                        "description = CASE WHEN description IS NULL OR TRIM(description) = '' "
                        "THEN :description ELSE description END WHERE id = :id"
                    ),
                    {"name": name, "bot": bot, "now": now, "description": description, "id": existing["id"]},
                )
                built_in_ids.add(existing["id"])
            continue
        bind.execute(
            sa.text(
                "INSERT INTO topics (name, description, owner_user_id, created_at, updated_at, "
                "archived, parent_topic_id, bot_key, origin) "
                "VALUES (:name, :description, :owner, :now, :now, 0, NULL, :bot, 'built_in')"
            ),
            {"name": name, "description": description, "owner": owner, "now": now, "bot": bot},
        )

    # 3. The v1 catch-all stays built in, but belongs to no bot (retired in 014).
    catch_all = by_name.get(CATCH_ALL.lower())
    if catch_all is not None:
        bind.execute(
            sa.text("UPDATE topics SET origin = 'built_in', bot_key = NULL WHERE id = :id"),
            {"id": catch_all["id"]},
        )
        built_in_ids.add(catch_all["id"])

    # 4. The user's own topics (and v1 AI-created ones) get a bot. Built-ins are
    # recognised by name: steps 1-3 gave every default its exact name.
    topics = _load_topics(bind, owner)
    built_in_bot = {name.lower(): bot for name, bot in DEFAULT_BOT.items()}
    built_in_bot[CATCH_ALL.lower()] = None

    def is_built_in(topic: dict) -> bool:
        return topic["name"].strip().lower() in built_in_bot

    bot_of = {
        topic["id"]: built_in_bot[topic["name"].strip().lower()]
        for topic in topics
        if is_built_in(topic)
    }
    others = [topic for topic in topics if not is_built_in(topic)]
    for topic in sorted(others, key=lambda t: t["parent_topic_id"] is not None):
        if topic["parent_topic_id"] is not None:
            bot = bot_of.get(topic["parent_topic_id"])
        else:
            bot = _bot_for_text(f"{topic['name']} {topic['description'] or ''}")
        bot_of[topic["id"]] = bot
        origin = "ai" if (topic["description"] or "").strip() == AI_CREATED_DESCRIPTION else "user"
        bind.execute(
            sa.text("UPDATE topics SET bot_key = :bot, origin = :origin WHERE id = :id"),
            {"bot": bot, "origin": origin, "id": topic["id"]},
        )


def _merge_topic(bind, source_id: int, target_id: int) -> None:
    """Move everything that points at `source_id` onto `target_id`, then drop it."""
    bind.execute(sa.text("UPDATE item_insights SET topic_id = :target WHERE topic_id = :source"),
                 {"target": target_id, "source": source_id})
    bind.execute(sa.text("UPDATE item_insights SET user_topic_id = :target WHERE user_topic_id = :source"),
                 {"target": target_id, "source": source_id})
    bind.execute(
        sa.text("UPDATE topics SET parent_topic_id = :target WHERE parent_topic_id = :source AND id != :target"),
        {"target": target_id, "source": source_id},
    )
    bind.execute(sa.text("DELETE FROM topics WHERE id = :source"), {"source": source_id})


def _rename_category(bind, owner, old: str, new: str) -> None:
    """Keep saved categories and the stored analysis view in step with the rename."""
    clause, params = _owner_clause(owner)
    bind.execute(
        sa.text(
            "UPDATE item_insights SET category = :new WHERE category = :old "
            f"AND item_id IN (SELECT id FROM inbox_items WHERE {clause})"
        ),
        {**params, "new": new, "old": old},
    )
    runs = bind.execute(
        sa.text(f"SELECT id, result_json FROM analysis_runs WHERE {clause} AND result_json IS NOT NULL"),
        params,
    ).mappings().all()
    for run in runs:
        try:
            stored = json.loads(run["result_json"])
        except (TypeError, ValueError):
            continue
        buckets = stored.get("buckets") if isinstance(stored, dict) else None
        if not isinstance(buckets, list):
            continue
        changed = False
        merged: list = []
        by_key: dict = {}
        for bucket in buckets:
            if not isinstance(bucket, dict):
                merged.append(bucket)
                continue
            if str(bucket.get("name", "")).strip().lower() == old.lower():
                bucket["name"] = new
                changed = True
            key = str(bucket.get("name", "")).strip().lower()
            if key in by_key:
                by_key[key].setdefault("notes", []).extend(bucket.get("notes") or [])
                changed = True
            else:
                by_key[key] = bucket
                merged.append(bucket)
        if changed:
            stored["buckets"] = merged
            bind.execute(
                sa.text("UPDATE analysis_runs SET result_json = :json WHERE id = :id"),
                {"json": json.dumps(stored, ensure_ascii=False), "id": run["id"]},
            )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: renamed and merged topics can't be safely restored. "
        "Restore from backup instead."
    )
