"""Hobbies, with Cooking inside it (the owner's request, 2026-11-08).

The built-in "Cooking & hobbies" (Fun & interests) becomes "Hobbies", and a
built-in subtopic "Cooking" is added under it. Notes the AI filed there that
are about food move into Cooking; the others stay in Hobbies. Notes you placed
yourself stay where you put them. An existing top-level topic of yours named
"Cooking" becomes the subtopic instead of a new one being made. The saved
analysis view is renamed to match.

Revision ID: 0026_hobbies_and_cooking
Revises: 0025_task_ideas
"""

import re
from datetime import datetime, timezone
from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0026_hobbies_and_cooking"
down_revision: Optional[str] = "0025_task_ideas"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None

OLD = "Cooking & hobbies"
HOBBIES = ("Hobbies", "Games, crafts, music you play, sport, collecting and other creative pursuits.")
COOKING = ("Cooking", "Recipes to try, dishes to cook, cooking ideas and kitchen tips.")
FOOD = re.compile(
    r"\b(recipes?|cook(ing|ed)?|bake|baking|dish(es)?|curry|biryani|pasta|paneer|chicken|dal|roti|"
    r"masala|sauce|soup|cake|dessert|kitchen|tikka|butter chicken)\b",
    re.I,
)


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc).isoformat()
    rows = bind.execute(sa.text(
        "SELECT id, owner_user_id FROM topics WHERE name = :old AND origin = 'built_in'"), {"old": OLD}).all()
    for hobbies_id, owner in rows:
        clash = bind.execute(sa.text(
            "SELECT id FROM topics WHERE lower(name) = 'hobbies' AND id != :id AND "
            "(owner_user_id = :owner OR (owner_user_id IS NULL AND :owner IS NULL))"),
            {"id": hobbies_id, "owner": owner}).first()
        name = HOBBIES[0] if clash is None else "Hobbies (built-in)"
        bind.execute(sa.text("UPDATE topics SET name = :name, description = :description, updated_at = :now WHERE id = :id"),
                     {"name": name, "description": HOBBIES[1], "now": now, "id": hobbies_id})
        mine = bind.execute(sa.text(
            "SELECT id FROM topics WHERE lower(name) = 'cooking' AND "
            "(owner_user_id = :owner OR (owner_user_id IS NULL AND :owner IS NULL))"), {"owner": owner}).first()
        if mine is not None:
            cooking_id = mine[0]
            bind.execute(sa.text("UPDATE topics SET parent_topic_id = :parent, bot_key = 'fun', updated_at = :now "
                                 "WHERE id = :id AND parent_topic_id IS NULL"),
                         {"parent": hobbies_id, "now": now, "id": cooking_id})
        else:
            bind.execute(sa.text(
                "INSERT INTO topics (name, description, owner_user_id, created_at, updated_at, archived, "
                "parent_topic_id, bot_key, origin) VALUES (:name, :description, :owner, :now, :now, 0, :parent, "
                "'fun', 'built_in')"),
                {"name": COOKING[0], "description": COOKING[1], "owner": owner, "now": now, "parent": hobbies_id})
            cooking_id = bind.execute(sa.text(
                "SELECT id FROM topics WHERE name = :name AND parent_topic_id = :parent"),
                {"name": COOKING[0], "parent": hobbies_id}).scalar()
        # Food notes the AI put there move into Cooking; the rest stay in Hobbies.
        notes = bind.execute(sa.text(
            "SELECT n.item_id, coalesce(i.raw_text, '') || ' ' || coalesce(i.title, '') || ' ' || "
            "coalesce(i.user_context, '') || ' ' || coalesce(n.concise_title, '') FROM item_insights n "
            "JOIN inbox_items i ON i.id = n.item_id WHERE n.topic_id = :id"), {"id": hobbies_id}).all()
        for item_id, words in notes:
            topic_id, category = (cooking_id, COOKING[0]) if FOOD.search(words or "") else (hobbies_id, name)
            bind.execute(sa.text("UPDATE item_insights SET topic_id = :topic, category = :category WHERE item_id = :item"),
                         {"topic": topic_id, "category": category, "item": item_id})
    # The saved "organized inbox" view uses the new name.
    bind.execute(sa.text(
        "UPDATE analysis_runs SET result_json = replace(result_json, :old, :new) WHERE result_json LIKE :like"),
        {"old": f'"name": "{OLD}"', "new": f'"name": "{HOBBIES[0]}"', "like": f"%{OLD}%"})


def downgrade() -> None:
    raise RuntimeError("Downgrade disabled: restore from backup instead.")
