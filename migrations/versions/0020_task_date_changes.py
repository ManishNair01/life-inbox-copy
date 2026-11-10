"""Task dates you can always change, with their history.

- `task_date_changes`: one row each time a task's date is set, postponed,
  moved earlier, confirmed, or moved because you edited its note. The note
  page lists them as "Updates" (change 012), and the export includes them.
  Rows keep the note (`item_id`) and the task's text, so the history stays
  even if analysis later replaces the task.
- `tasks.date_recheck`: set when you edit a note whose task date you had
  confirmed. The next analysis of that note may then move the date to what
  your new text says, and asks you to confirm it again. Without an edit, a
  confirmed date never moves.

Revision ID: 0020_task_date_changes
Revises: 0019_task_priority_and_done
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_task_date_changes"
down_revision: Optional[str] = "0019_task_priority_and_done"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None

KINDS = ("set", "postponed", "moved_earlier", "confirmed", "note_edit")


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tasks")}
    if "date_recheck" not in columns:
        op.execute("ALTER TABLE tasks ADD COLUMN date_recheck INTEGER NOT NULL DEFAULT 0")
    if "task_date_changes" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "task_date_changes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        # No foreign key: the history outlives a task that analysis replaces.
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("task_text", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("from_due_on", sa.Text(), nullable=True),
        sa.Column("from_due_time", sa.Text(), nullable=True),
        sa.Column("to_due_on", sa.Text(), nullable=True),
        sa.Column("to_due_time", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('set', 'postponed', 'moved_earlier', 'confirmed', 'note_edit')",
            name="ck_task_date_changes_kind",
        ),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_task_date_changes_item", "task_date_changes", ["owner_user_id", "item_id"])
    op.create_index("ix_task_date_changes_task", "task_date_changes", ["task_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: it would delete the history of your task dates. "
        "Restore from backup instead."
    )
