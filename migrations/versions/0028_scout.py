"""Scout, the catch-up helper (change 018).

- `task_events`: what happened to a task and who did it. Kind: done,
  rescheduled, dropped (with an optional reason, decision M), someday, kept
  (still someday) or reopened; by you or by Scout; the day it was on and the
  day it moved to.
- `tasks.someday` / `tasks.someday_since`: a task you'll do some day. It has
  no date, so it stays off the calendar, Timeline and reminders, and Priority
  shows it apart. Scout asks about it again after a month.
- `user_settings.away_days`: how long you were away when you came back (7+
  days), so Scout's "You've been away 9 days" stays until you finish the
  catch-up. The catch-up day and time came in 0027.

Revision ID: 0028_scout
Revises: 0027_memory
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0028_scout"
down_revision: Optional[str] = "0027_memory"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "task_events" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "task_events",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("by", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("from_due_on", sa.Text(), nullable=True),
            sa.Column("to_due_on", sa.Text(), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.CheckConstraint("kind IN ('done', 'rescheduled', 'dropped', 'someday', 'kept', 'reopened')",
                               name="ck_task_events_kind"),
            sa.CheckConstraint("by IN ('you', 'scout')", name="ck_task_events_by"),
            sqlite_autoincrement=True,
        )
        op.create_index("ix_task_events_owner_task", "task_events", ["owner_user_id", "task_id"])
    # Plain ADD COLUMN (as 0021 and 0024 do): the tables aren't rebuilt.
    if "someday" not in _columns(bind, "tasks"):
        op.execute("ALTER TABLE tasks ADD COLUMN someday INTEGER NOT NULL DEFAULT 0")
    if "someday_since" not in _columns(bind, "tasks"):
        op.execute("ALTER TABLE tasks ADD COLUMN someday_since TEXT")
    if "away_days" not in _columns(bind, "user_settings"):
        op.execute("ALTER TABLE user_settings ADD COLUMN away_days INTEGER")


def downgrade() -> None:
    with op.batch_alter_table("user_settings") as batch:
        batch.drop_column("away_days")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("someday_since")
        batch.drop_column("someday")
    op.drop_index("ix_task_events_owner_task", table_name="task_events")
    op.drop_table("task_events")
