"""Remember when a user edited a task so re-analysis does not overwrite it.

Revision ID: 0016_task_user_edited
Revises: 0015_google_signin
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_task_user_edited"
down_revision: Optional[str] = "0015_google_signin"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "user_edited" not in columns:
        with op.batch_alter_table("tasks") as batch:
            batch.add_column(
                sa.Column(
                    "user_edited",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading would lose user-edited task flags; restore from backup."
    )
