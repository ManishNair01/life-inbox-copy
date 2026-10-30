"""Add a version counter to inbox items for optimistic edit-conflict detection.

Revision ID: 0014_item_version
Revises: 0013_one_running_analysis
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_item_version"
down_revision: Optional[str] = "0013_one_running_analysis"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("inbox_items")}
    if "version" not in columns:
        with op.batch_alter_table("inbox_items") as batch:
            batch.add_column(
                sa.Column(
                    "version",
                    sa.Integer(),
                    nullable=False,
                    server_default="1",
                )
            )


def downgrade() -> None:
    with op.batch_alter_table("inbox_items") as batch:
        batch.drop_column("version")
