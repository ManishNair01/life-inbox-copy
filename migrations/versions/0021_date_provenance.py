"""Where each task date came from (change 012).

- `tasks.due_confidence` now says where the date stands:
  - `from_note`: your words named the day ("tomorrow", "12 Nov");
  - `suggested`: Life Inbox guessed it ("this weekend", "Friday"), so it
    waits for your OK;
  - `user_confirmed`: you confirmed or set it.
- `tasks.suggested_due_on` / `suggested_due_time` hold a guess. A guess stays
  off `due_on`, so it never reaches the calendar or reminders until you
  confirm it.

Existing tasks are sorted the same way: confirmed ones become
`user_confirmed`; the others keep their date if the words name the day, and
otherwise their date becomes a suggestion.

Revision ID: 0021_date_provenance
Revises: 0020_task_date_changes
"""

import re
from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_date_provenance"
down_revision: Optional[str] = "0020_task_date_changes"
branch_labels: Optional[Union[str, Sequence[str]]] = None
depends_on: Optional[Union[str, Sequence[str]]] = None

# Copied (not imported) from app/attention/dates.py on 2026-11-07, so this
# migration never changes when the app's date reader does.
_MONTH = (
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_NAMED_DAY = (
    re.compile(r"\btoday\b", re.I),
    re.compile(r"\btomorrow\b", re.I),
    re.compile(r"\b20\d{2}-\d{2}-\d{2}\b"),
    re.compile(r"\bin\s+\d+\s+days?\b", re.I),
    re.compile(_MONTH + r"\s+\d{1,2}(?:st|nd|rd|th)?\b", re.I),
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH, re.I),
)


def _names_the_day(text: Optional[str]) -> bool:
    lower = (text or "").lower()
    if "asap" in lower or "urgent" in lower or "weekend" in lower:
        return False
    return any(pattern.search(lower) for pattern in _NAMED_DAY)


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("tasks")}
    if "suggested_due_on" not in columns:
        op.execute("ALTER TABLE tasks ADD COLUMN suggested_due_on TEXT")
    if "suggested_due_time" not in columns:
        op.execute("ALTER TABLE tasks ADD COLUMN suggested_due_time TEXT")
    rows = bind.execute(sa.text(
        "SELECT id, timing_text, due_on, due_time, due_confidence, timing_confirmed FROM tasks"
    )).mappings().all()
    for row in rows:
        if row["due_confidence"] in ("from_note", "suggested", "user_confirmed"):
            continue  # already sorted
        if row["timing_confirmed"] and row["due_on"]:
            values = {"conf": "user_confirmed", "on": row["due_on"], "time": row["due_time"], "s_on": None, "s_time": None}
        elif not row["due_on"]:
            values = {"conf": None, "on": None, "time": None, "s_on": None, "s_time": None}
        elif row["due_confidence"] == "high" or _names_the_day(row["timing_text"]):
            values = {"conf": "from_note", "on": row["due_on"], "time": row["due_time"], "s_on": None, "s_time": None}
        else:
            values = {"conf": "suggested", "on": None, "time": None, "s_on": row["due_on"], "s_time": row["due_time"]}
        bind.execute(
            sa.text(
                "UPDATE tasks SET due_confidence = :conf, due_on = :on, due_time = :time, "
                "suggested_due_on = :s_on, suggested_due_time = :s_time WHERE id = :id"
            ),
            {**values, "id": row["id"]},
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade disabled: suggested dates would be lost. Restore from backup instead."
    )
