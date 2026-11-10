"""Add Google sign-in identity to users.

Revision ID: 0015_google_signin
Revises: 0014_notifications
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015_google_signin"
down_revision: Optional[str] = "0014_notifications"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None

INDEX_NAME = "uq_users_google_sub"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("users")}
    if "google_sub" not in columns:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("google_sub", sa.Text(), nullable=True))
    indexes = {index["name"] for index in inspector.get_indexes("users")}
    if INDEX_NAME not in indexes:
        # Several NULLs are allowed; each Google account maps to one user.
        op.create_index(INDEX_NAME, "users", ["google_sub"], unique=True)


def downgrade() -> None:
    raise RuntimeError(
        "Downgrading would drop linked Google identities; restore from backup."
    )
