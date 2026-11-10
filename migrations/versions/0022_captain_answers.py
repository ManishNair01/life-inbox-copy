"""Captain's "Needs you" answers (change 013).

`captain_answers` keeps the answer you give each "Needs you" card: "Not now",
the topic or life area you picked, a capture you deleted, a task you dropped.
One row per card (`card_key`), so an answered card doesn't come back. A card
whose situation changes gets a new key (a guessed date that moves to another
day asks again). Change 016 turns these answers into memory examples.

Revision ID: 0022_captain_answers
Revises: 0021_date_provenance
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022_captain_answers"
down_revision: Optional[str] = "0021_date_provenance"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "captain_answers" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "captain_answers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("card_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        # JSON: what the card showed and what you chose (for memory examples, 016).
        sa.Column("detail", sa.Text(), nullable=True),
        # No foreign keys: the answer outlives a note, task or topic you delete.
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("topic_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("owner_user_id", "card_key", name="uq_captain_answers_card"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_captain_answers_owner_item", "captain_answers", ["owner_user_id", "item_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: it would forget your answers to Captain's questions. "
        "Restore from backup instead."
    )
