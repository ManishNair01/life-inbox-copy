"""Thought-to-action (change 014a): actions that aren't commitments yet.

`task_ideas` keeps an action filing found in your words that you didn't
commit to: a tentative plan ("I should probably call Rahul") that Captain asks
about before it becomes a task, or a someday idea ("visit this dhaba next time
I'm on that route") that just stays with its note. Neither is a task, so they
never reach the calendar, reminders or Priority. "Add task" turns one into a
real task.

Revision ID: 0025_task_ideas
Revises: 0024_link_cards
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0025_task_ideas"
down_revision: Optional[str] = "0024_link_cards"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "task_ideas" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "task_ideas",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("inbox_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("timing_text", sa.Text(), nullable=True),
        sa.Column("intent", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="waiting"),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("intent IN ('tentative', 'someday')", name="ck_task_ideas_intent"),
        sa.CheckConstraint("status IN ('waiting', 'added', 'dismissed')", name="ck_task_ideas_status"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_task_ideas_owner_item", "task_ideas", ["owner_user_id", "item_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: it would forget the ideas found in your notes. Restore from backup instead."
    )
