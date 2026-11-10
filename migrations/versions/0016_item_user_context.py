"""Sources can carry the user's own note ("context") about why they were saved.

Kept in its own column so the user's words stay separate from the source's
original and extracted text.

Revision ID: 0016_item_user_context
Revises: 0015_topic_hierarchy
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_item_user_context"
down_revision: Optional[str] = "0015_topic_hierarchy"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    columns = {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("inbox_items")
    }
    if "user_context" not in columns:
        with op.batch_alter_table("inbox_items") as batch:
            batch.add_column(sa.Column("user_context", sa.Text(), nullable=True))


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: it would delete users' notes on their sources. "
        "Restore from backup instead."
    )
