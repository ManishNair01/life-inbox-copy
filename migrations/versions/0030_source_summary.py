"""A long PDF's one-time summary (change 022, decision P).

- `inbox_items.source_summary`: an AI summary of a long saved document, made
  once when it's read (not on every re-filing). AI output, kept apart from the
  document's own text and from your note; filing sees it before the start of
  the text, so a long document is filed by what it covers, not its first page.

Revision ID: 0030_source_summary
Revises: 0029_weekly_review
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0030_source_summary"
down_revision: Optional[str] = "0029_weekly_review"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    bind = op.get_bind()
    if "source_summary" not in {column["name"] for column in sa.inspect(bind).get_columns("inbox_items")}:
        op.execute("ALTER TABLE inbox_items ADD COLUMN source_summary TEXT")


def downgrade() -> None:
    with op.batch_alter_table("inbox_items") as batch:
        batch.drop_column("source_summary")
