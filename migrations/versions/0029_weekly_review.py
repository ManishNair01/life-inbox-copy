"""Weekly review, topic proposals, bot summaries and the daily greeting (change 020).

- `topics.proposed_by` / `evidence_item_ids` / `approved_at`: a topic's history
  when it came from a proposal ("Suggested by the Learning & work bot from
  notes #12, #14, #15; approved by you on …").
- `topic_proposals`: a group of 3+ notes in one area that no topic fits, named
  by the weekly call, waiting for you: pending, created, declined (Not now) or
  never (Don't suggest this; its word signature is remembered).
- `bot_summaries`: each life area's summary line, with a key of what the area
  held when it was written; rewritten only when that changes.
- `greetings`: Captain's AI greeting, one per user per local day (decision N).

Revision ID: 0029_weekly_review
Revises: 0028_scout
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0029_weekly_review"
down_revision: Optional[str] = "0028_scout"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    for column, kind in (("proposed_by", "TEXT"), ("evidence_item_ids", "TEXT"), ("approved_at", "TEXT")):
        if column not in _columns(bind, "topics"):
            op.execute(f"ALTER TABLE topics ADD COLUMN {column} {kind}")
    if "topic_proposals" not in tables:
        op.create_table(
            "topic_proposals",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("bot_key", sa.Text(), nullable=False),
            sa.Column("name", sa.Text(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("parent_topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
            sa.Column("item_ids", sa.Text(), nullable=False),
            sa.Column("signature", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
            sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.CheckConstraint("status IN ('pending', 'created', 'declined', 'never')", name="ck_topic_proposals_status"),
            sqlite_autoincrement=True,
        )
        op.create_index("ix_topic_proposals_owner_status", "topic_proposals", ["owner_user_id", "status"])
    if "bot_summaries" not in tables:
        op.create_table(
            "bot_summaries",
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("bot_key", sa.Text(), primary_key=True),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("data_key", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )
    if "greetings" not in tables:
        op.create_table(
            "greetings",
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("day", sa.Text(), primary_key=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("greetings")
    op.drop_table("bot_summaries")
    op.drop_index("ix_topic_proposals_owner_status", table_name="topic_proposals")
    op.drop_table("topic_proposals")
    with op.batch_alter_table("topics") as batch:
        batch.drop_column("approved_at")
        batch.drop_column("evidence_item_ids")
        batch.drop_column("proposed_by")
