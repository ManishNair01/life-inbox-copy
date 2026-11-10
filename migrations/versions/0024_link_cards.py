"""Link cards (change 015): what Life Inbox read from a saved link, by code.

`inbox_items.link_card` holds a JSON card of at most 1,500 characters of text:
the kind (video, recipe, article, event, page), the exact title, the site or
channel, facts from the page's own structured data (a recipe's ingredients and
steps, an article's date and author, an event's date and place), and the main
text without menus, footers and cookie banners. No AI writes it: it is the
"source" the filing call sees for a link, kept apart from the AI's output.

Revision ID: 0024_link_cards
Revises: 0023_filing_v2
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024_link_cards"
down_revision: Optional[str] = "0023_filing_v2"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("inbox_items")}
    if "link_card" not in existing:
        op.execute("ALTER TABLE inbox_items ADD COLUMN link_card TEXT")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: it would forget what was read from your saved links. "
        "Restore from backup instead."
    )
