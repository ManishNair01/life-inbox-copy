"""Log every AI request: who, which action, model, outcome and sizes.

Never the prompt or answer text. Used to count calls per action (target: at
most 1.2 per added note) and to see provider errors such as NVIDIA's 404.

Revision ID: 0017_ai_call_log
Revises: 0016_item_user_context
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_ai_call_log"
down_revision: Optional[str] = "0016_item_user_context"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "ai_calls" in tables:
        return
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("input_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('ok', 'invalid', 'error', 'too_large')",
            name="ck_ai_calls_outcome",
        ),
        sqlite_autoincrement=True,
    )
    op.create_index(
        "ix_ai_calls_owner_created", "ai_calls", ["owner_user_id", "created_at"]
    )


def downgrade() -> None:
    # Only usage counts are lost; no note, topic or memory lives here.
    op.drop_index("ix_ai_calls_owner_created", table_name="ai_calls")
    op.drop_table("ai_calls")
