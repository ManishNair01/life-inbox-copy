"""Tasks keep the priority you chose, and when they were done.

- `user_priority`: dragging a task to another column on the Priority view
  (change 011) stores your choice here. Analysis keeps updating `priority`
  (the AI's value) but never overwrites yours; the app shows yours when set.
- `completed_at`: when the task was completed (cleared if reopened), so the
  Dashboard can count "tasks done this week". `updated_at` can't: analysis
  also touches it. Tasks already done get their last update time as the best
  guess there is.

Revision ID: 0019_task_priority_and_done
Revises: 0018_five_life_areas
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_task_priority_and_done"
down_revision: Optional[str] = "0018_five_life_areas"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("tasks")}
    # Plain ADD COLUMNs (the first with a column-level CHECK): no table rebuild,
    # so the tasks table keeps its other constraints and AUTOINCREMENT exactly.
    if "user_priority" not in columns:
        op.execute(
            "ALTER TABLE tasks ADD COLUMN user_priority TEXT "
            "CONSTRAINT ck_tasks_user_priority "
            "CHECK (user_priority IS NULL OR user_priority IN ('High', 'Medium', 'Low'))"
        )
    if "completed_at" not in columns:
        op.execute("ALTER TABLE tasks ADD COLUMN completed_at TEXT")
        op.execute("UPDATE tasks SET completed_at = updated_at WHERE status = 'completed'")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: it would delete the priorities users chose for their "
        "tasks. Restore from backup instead."
    )
