"""Subtopics: topics can sit under one parent topic; built-in topics get descriptions.

Revision ID: 0015_topic_hierarchy
Revises: 0014_notifications
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_topic_hierarchy"
down_revision: Optional[str] = "0014_notifications"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


# Kept in sync with DEFAULT_TOPIC_DESCRIPTIONS in app/database.py. Only fills
# descriptions that are still empty, so user edits are never overwritten.
BUILT_IN_DESCRIPTIONS = {
    "Work": "Job, meetings, colleagues, projects, interviews and career.",
    "Money & Admin": "Bills, taxes, insurance, banking, paperwork and subscriptions.",
    "Learning": "Things to read, watch, study or look into; courses and articles.",
    "Shopping & Errands": "Things to buy, pick up, order or get done around town.",
    "Health": "Doctors, medicines, fitness, diet, sleep and wellbeing.",
    "Travel": "Trips, bookings, flights, hotels and places to visit.",
    "Ideas": "Product, business and creative ideas worth keeping.",
    "People": "Friends and family: calls, follow-ups, birthdays and favours.",
    "Personal / Reference": "Everything else worth remembering for later.",
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("topics")}
    if "parent_topic_id" not in columns:
        with op.batch_alter_table("topics") as batch:
            batch.add_column(
                sa.Column("parent_topic_id", sa.Integer(), nullable=True)
            )
            batch.create_foreign_key(
                "fk_topics_parent_topic_id",
                "topics",
                ["parent_topic_id"],
                ["id"],
                ondelete="SET NULL",
            )
    for name, description in BUILT_IN_DESCRIPTIONS.items():
        bind.execute(
            sa.text(
                "UPDATE topics SET description = :description "
                "WHERE name = :name AND (description IS NULL OR description = '')"
            ),
            {"name": name, "description": description},
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled to protect topic organization; restore from backup."
    )
