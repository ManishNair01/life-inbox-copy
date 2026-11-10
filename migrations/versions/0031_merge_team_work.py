"""Join the two lines of migrations (no schema change).

Life Inbox v2 (0015_topic_hierarchy … 0030_source_summary) and the team's
Google sign-in and task editing (0015_google_signin, 0016_task_user_edited)
both grew from 0014_notifications. This revision makes them one line again, so
a database on either side upgrades to the same head.

Revision ID: 0031_merge_team_work
Revises: 0030_source_summary, 0016_task_user_edited
"""

from typing import Optional, Sequence, Union

revision: str = "0031_merge_team_work"
down_revision: Union[str, Sequence[str], None] = ("0030_source_summary", "0016_task_user_edited")
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
