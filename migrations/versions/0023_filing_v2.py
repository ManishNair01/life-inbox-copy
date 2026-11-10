"""Filing v2 (change 014): how each note was filed, and what the AI added.

New `item_insights` columns:
- `filing_rule`: the rule that decided (R1-R6, design section 4.1);
- `filing_confidence`: high, medium or low;
- `filing_choices`: JSON list of the two likeliest topic ids when it was unsure;
- `filed_by`: ai, offline (the matcher without AI) or you;
- `filing_pending`: 1 while the note waits for your pick in Captain's "Needs
  you" list; it has no topic until then (rule R6, "don't guess");
- `ai_summary`, `suggested_action`: a source's two-sentence summary and a
  suggested next step ("Watch later"), both AI output;
- `cleaned_transcript`: a voice note's transcript tidied by the AI. The raw
  transcript stays in `inbox_items.extracted_text`.

Existing rows: `filed_by` is "you" where you picked the topic, "offline" where
the run had no AI, otherwise "ai".

Revision ID: 0023_filing_v2
Revises: 0022_captain_answers
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023_filing_v2"
down_revision: Optional[str] = "0022_captain_answers"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None

COLUMNS = (
    ("filing_rule", "TEXT"),
    ("filing_confidence", "TEXT"),
    ("filing_choices", "TEXT"),
    ("filed_by", "TEXT"),
    ("filing_pending", "INTEGER NOT NULL DEFAULT 0"),
    ("ai_summary", "TEXT"),
    ("suggested_action", "TEXT"),
    ("cleaned_transcript", "TEXT"),
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("item_insights")}
    for name, kind in COLUMNS:
        if name not in existing:
            op.execute(f"ALTER TABLE item_insights ADD COLUMN {name} {kind}")
    op.execute(
        """
        UPDATE item_insights SET filed_by = CASE
            WHEN user_topic_id IS NOT NULL THEN 'you'
            WHEN (SELECT mode FROM analysis_runs WHERE analysis_runs.id = item_insights.analysis_run_id)
                 LIKE 'fallback%' THEN 'offline'
            ELSE 'ai'
        END
        WHERE filed_by IS NULL
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: it would forget how your notes were filed. "
        "Restore from backup instead."
    )
