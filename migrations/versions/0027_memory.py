"""Memory (changes 016, 017), and the user settings later changes use.

- `memory_facts`: what Life Inbox learns about you. Kind: long_term (who you
  are, what you do), short_term (a plan, until its date) or example (a choice
  you made: a topic you moved a note to, a Needs you pick). Each fact keeps
  its source notes and where it came from, and its status: suggested,
  confirmed (by you, or seen again), expired, deleted. `text_key` (a hash of
  the normalised text) keeps a deleted fact from being suggested again; a
  deleted fact's text is erased.
- `user_settings`: health-memory consent (016, off until you allow it), the
  AI-processing switch (025, on for existing accounts), the weekly catch-up
  day and time (018), when you were last seen and last caught up (018), the
  last weekly review (020), and whether onboarding was done (024).
- `item_insights.memory_used`: which memory facts the filing call used (017).
- `plan_updates`: a note that changes a plan you already have ("Quiz moved to
  Thursday"), waiting for your Yes / No (017).

Revision ID: 0027_memory
Revises: 0026_hobbies_and_cooking
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0027_memory"
down_revision: Optional[str] = "0026_hobbies_and_cooking"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "memory_facts" not in tables:
        op.create_table(
            "memory_facts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("bot_key", sa.Text(), nullable=True),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("text_key", sa.Text(), nullable=False),
            sa.Column("source_item_ids", sa.Text(), nullable=True),
            sa.Column("source_kind", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("times_seen", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("valid_until", sa.Text(), nullable=True),
            sa.Column("core_profile", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.CheckConstraint("kind IN ('long_term', 'short_term', 'example')", name="ck_memory_facts_kind"),
            sa.CheckConstraint("status IN ('suggested', 'confirmed', 'expired', 'deleted')", name="ck_memory_facts_status"),
            sa.CheckConstraint(
                "source_kind IN ('your_words', 'correction', 'needs_you', 'scout', 'onboarding', 'weekly_review', 'you')",
                name="ck_memory_facts_source_kind",
            ),
            sa.UniqueConstraint("owner_user_id", "text_key", name="uq_memory_facts_text"),
            sqlite_autoincrement=True,
        )
        op.create_index("ix_memory_facts_owner_status", "memory_facts", ["owner_user_id", "status"])
    if "user_settings" not in tables:
        op.create_table(
            "user_settings",
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("health_memory_consent", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ai_processing", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("catchup_day", sa.Text(), nullable=False, server_default="sun"),
            sa.Column("catchup_time", sa.Text(), nullable=False, server_default="19:00"),
            sa.Column("last_seen_at", sa.Text(), nullable=True),
            sa.Column("last_catchup_at", sa.Text(), nullable=True),
            sa.Column("last_weekly_review_at", sa.Text(), nullable=True),
            sa.Column("onboarding_done", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.CheckConstraint("catchup_day IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')", name="ck_user_settings_day"),
        )
    columns = {column["name"] for column in sa.inspect(bind).get_columns("item_insights")}
    if "memory_used" not in columns:
        op.execute("ALTER TABLE item_insights ADD COLUMN memory_used TEXT")
    if "plan_updates" not in tables:
        op.create_table(
            "plan_updates",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("inbox_items.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("task_text", sa.Text(), nullable=False),
            sa.Column("new_task_text", sa.Text(), nullable=False),
            sa.Column("new_timing_text", sa.Text(), nullable=True),
            sa.Column("new_due_on", sa.Text(), nullable=True),
            sa.Column("new_due_time", sa.Text(), nullable=True),
            sa.Column("status", sa.Text(), nullable=False, server_default="waiting"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.CheckConstraint("status IN ('waiting', 'applied', 'declined')", name="ck_plan_updates_status"),
            sqlite_autoincrement=True,
        )


def downgrade() -> None:
    raise RuntimeError("Downgrade disabled: it would forget what Life Inbox learned. Restore from backup instead.")
