"""Add task times and notification delivery records.

Revision ID: 0014_notifications
Revises: 0013_otp_challenges
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_notifications"
down_revision: Optional[str] = "0013_otp_challenges"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {
        column["name"] for column in inspector.get_columns("tasks")
    }
    if "due_time" not in task_columns:
        with op.batch_alter_table("tasks") as batch:
            batch.add_column(sa.Column("due_time", sa.Text(), nullable=True))

    tables = set(inspector.get_table_names())
    if "notification_preferences" not in tables:
        op.create_table(
            "notification_preferences",
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "enabled", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column(
                "daily_digest_time",
                sa.Text(),
                nullable=False,
                server_default="08:00",
            ),
            sa.Column(
                "timezone", sa.Text(), nullable=False, server_default="UTC"
            ),
            sa.Column(
                "include_unscheduled_prompt",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )

    if "push_subscriptions" not in tables:
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("endpoint", sa.Text(), nullable=False),
            sa.Column("p256dh", sa.Text(), nullable=False),
            sa.Column("auth", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.UniqueConstraint(
                "endpoint", name="uq_push_subscriptions_endpoint"
            ),
        )
        op.create_index(
            "ix_push_subscriptions_user_id",
            "push_subscriptions",
            ["user_id"],
        )

    if "notification_deliveries" not in tables:
        op.create_table(
            "notification_deliveries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "task_id",
                sa.Integer(),
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("kind", sa.Text(), nullable=False),
            sa.Column("local_date", sa.Text(), nullable=False),
            sa.Column("idempotency_key", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column(
                "attempts", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.Column("delivered_at", sa.Text(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.UniqueConstraint(
                "idempotency_key",
                name="uq_notification_deliveries_idempotency_key",
            ),
        )
        op.create_index(
            "ix_notification_deliveries_user_id",
            "notification_deliveries",
            ["user_id"],
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade is disabled to preserve notification delivery history"
    )
