"""Record how each item relation was inferred (lexical vs semantic).

Revision ID: 0012_relation_method
Revises: 0011_multi_user_ownership
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012_relation_method"
down_revision: Optional[str] = "0011_multi_user_ownership"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("item_relations")}
    if "method" not in columns:
        with op.batch_alter_table("item_relations") as batch:
            batch.add_column(
                sa.Column(
                    "method",
                    sa.Text(),
                    nullable=False,
                    server_default="lexical",
                )
            )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is disabled to avoid dropping relation provenance"
    )
