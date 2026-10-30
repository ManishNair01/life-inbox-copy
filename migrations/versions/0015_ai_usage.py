"""Track Gemini calls per user per day for quotas.

Revision ID: 0015_ai_usage
Revises: 0014_item_version
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_ai_usage"
down_revision: Optional[str] = "0014_item_version"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    if "ai_usage" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "ai_usage",
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            primary_key=True,
        ),
        sa.Column("day", sa.Text(), primary_key=True),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("ai_usage")
