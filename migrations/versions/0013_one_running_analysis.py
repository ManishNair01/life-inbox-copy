"""Allow at most one running analysis per user.

Revision ID: 0013_one_running_analysis
Revises: 0012_relation_method
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_one_running_analysis"
down_revision: Optional[str] = "0012_relation_method"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None

INDEX_NAME = "uq_analysis_runs_one_running_per_owner"


def upgrade() -> None:
    bind = op.get_bind()
    existing = {ix["name"] for ix in sa.inspect(bind).get_indexes("analysis_runs")}
    if INDEX_NAME in existing:
        return
    # Runs still marked running belong to processes that died before this
    # migration; leaving them would make the unique index fail to build.
    op.execute(
        "UPDATE analysis_runs SET status = 'failed', mode = 'error' "
        "WHERE status = 'running'"
    )
    op.create_index(
        INDEX_NAME,
        "analysis_runs",
        ["owner_user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="analysis_runs")
