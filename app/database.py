import hashlib
import json
import os
import re
from contextvars import ContextVar
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
import uuid

_current_owner_id: ContextVar[Optional[int]] = ContextVar(
    "life_inbox_owner_id", default=None
)


class NotAuthenticatedError(RuntimeError):
    """Raised when owner-scoped data is touched without a signed-in user."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    or_,
    select,
    true,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.capture.pipeline import (
    ANALYZABLE_STATUSES,
    ANALYZABLE_TYPES,
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_PROCESSING,
    STATUS_READY,
    IMAGE_ITEM_TYPE,
    PDF_ITEM_TYPE,
    URL_ITEM_TYPE,
    VOICE_ITEM_TYPE,
)
from app import bots
from app.capture.storage import delete_stored_file
from app.similarity import find_item_relations


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "life_inbox.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
AUTO_CREATE_TABLES = os.getenv(
    "LIFE_INBOX_AUTO_CREATE_TABLES", ""
).strip().lower() in {"1", "true", "yes"}


def _connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(DATABASE_URL, connect_args=_connect_args(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite only enforces CASCADE when foreign_keys pragma is on."""
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


TEXT_ITEM_TYPE = "text"
READY_STATUS = STATUS_READY
ANALYSIS_RUNNING = "running"
ANALYSIS_SUCCEEDED = "succeeded"
ANALYSIS_FAILED = "failed"
TASK_OPEN = "open"
TASK_COMPLETED = "completed"
TASK_DISMISSED = "dismissed"
TASK_STATUSES = {TASK_OPEN, TASK_COMPLETED, TASK_DISMISSED}
DEFAULT_OWNER_EMAIL = "local@life-inbox.local"


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("uq_users_google_sub", "google_sub", unique=True),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(Text, nullable=False)
    display_name = Column(Text, nullable=False)
    auth_provider = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    password_hash = Column(Text, nullable=True)
    password_changed_at = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="active", server_default="active")
    failed_password_attempts = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until = Column(Text, nullable=True)
    last_login_at = Column(Text, nullable=True)
    email_verified_at = Column(Text, nullable=True)
    adult_confirmed_at = Column(Text, nullable=True)
    terms_accepted_at = Column(Text, nullable=True)
    google_sub = Column(Text, nullable=True)


class AuthSessionRecord(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash = Column(Text, nullable=False)
    auth_method = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    last_seen_at = Column(Text, nullable=False)
    idle_expires_at = Column(Text, nullable=False)
    absolute_expires_at = Column(Text, nullable=False)
    revoked_at = Column(Text, nullable=True)
    revoked_reason = Column(Text, nullable=True)
    device_label = Column(Text, nullable=True)


class OtpChallengeRecord(Base):
    __tablename__ = "otp_challenges"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    purpose = Column(Text, nullable=False)
    identifier_hash = Column(Text, nullable=False, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    code_hash = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=5, server_default="5")
    created_at = Column(Text, nullable=False)
    expires_at = Column(Text, nullable=False)
    consumed_at = Column(Text, nullable=True)


class InboxItemRecord(Base):
    __tablename__ = "inbox_items"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_type = Column(Text, nullable=False)
    title = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    original_filename = Column(Text, nullable=True)
    mime_type = Column(Text, nullable=True)
    processing_status = Column(Text, nullable=False)
    error_message = Column(Text, nullable=True)
    storage_path = Column(Text, nullable=True)
    extracted_text = Column(Text, nullable=True)
    ai_description = Column(Text, nullable=True)
    # The user's own note about why they saved this source (never AI-written).
    user_context = Column(Text, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=True)
    # What code read from a saved link (change 015, migration 0024): JSON card
    # with at most 1,500 characters of text. Not AI output.
    link_card = Column(Text, nullable=True)
    # A long PDF's one-time AI summary (change 022, decision P).
    source_summary = Column(Text, nullable=True)


class AnalysisRunRecord(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(Text, nullable=False)
    completed_at = Column(Text, nullable=True)
    status = Column(Text, nullable=False)
    mode = Column(Text, nullable=False)
    result_json = Column(Text, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)


class TopicRecord(Base):
    __tablename__ = "topics"
    __table_args__ = (
        UniqueConstraint("name", "owner_user_id", name="uq_topics_name_owner"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    archived = Column(Integer, nullable=False, default=0)
    # One level only: a subtopic's parent is always a top-level topic.
    parent_topic_id = Column(
        Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
    )
    # The life area (app/bots.py) the topic belongs to; NULL means none yet.
    bot_key = Column(Text, nullable=True)
    # built_in (a default topic), user (made by the user) or ai (v1 analysis).
    origin = Column(Text, nullable=False, default="user", server_default="user")
    # Its history when it came from a proposal (change 020): the area that
    # suggested it, the notes it was suggested from, and when you approved it.
    proposed_by = Column(Text, nullable=True)
    evidence_item_ids = Column(Text, nullable=True)
    approved_at = Column(Text, nullable=True)


class ItemInsightRecord(Base):
    __tablename__ = "item_insights"

    item_id = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        primary_key=True,
    )
    analysis_run_id = Column(
        Integer,
        ForeignKey("analysis_runs.id"),
        nullable=False,
    )
    category = Column(Text, nullable=False)
    concise_title = Column(Text, nullable=False)
    priority = Column(Text, nullable=False)
    topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    tags_json = Column(Text, nullable=True)
    rationale = Column(Text, nullable=True)
    user_title = Column(Text, nullable=True)
    user_topic_id = Column(Integer, ForeignKey("topics.id"), nullable=True)
    user_priority = Column(Text, nullable=True)
    user_tags_json = Column(Text, nullable=True)
    needs_review = Column(Integer, nullable=False, default=0)
    updated_at = Column(Text, nullable=False)
    # Filing v2 (change 014, migration 0023): how the note was filed.
    filing_rule = Column(Text, nullable=True)  # R1-R6
    filing_confidence = Column(Text, nullable=True)  # high / medium / low
    filing_choices = Column(Text, nullable=True)  # JSON: up to 2 topic ids
    filed_by = Column(Text, nullable=True)  # ai / offline / you
    # 1 while the note waits for your pick in "Needs you": no topic until then.
    filing_pending = Column(Integer, nullable=False, default=0, server_default="0")
    ai_summary = Column(Text, nullable=True)  # AI output: a source's summary
    suggested_action = Column(Text, nullable=True)  # AI output: "Watch later"
    cleaned_transcript = Column(Text, nullable=True)  # AI output: tidied voice transcript
    memory_used = Column(Text, nullable=True)  # JSON: memory facts the filing call used (017)


class ItemRelationRecord(Base):
    __tablename__ = "item_relations"
    __table_args__ = (
        UniqueConstraint(
            "item_id_a",
            "item_id_b",
            "relation_type",
            name="uq_item_relations_pair_type",
        ),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id_a = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id_b = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type = Column(Text, nullable=False)
    score = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    dismissed = Column(Integer, nullable=False, default=0)


class TaskRecord(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "priority IN ('High', 'Medium', 'Low')",
            name="ck_tasks_priority",
        ),
        CheckConstraint(
            "status IN ('open', 'completed', 'dismissed')",
            name="ck_tasks_status",
        ),
        CheckConstraint(
            "user_priority IS NULL OR user_priority IN ('High', 'Medium', 'Low')",
            name="ck_tasks_user_priority",
        ),
        UniqueConstraint("dedup_key"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    # The AI's priority; analysis keeps it up to date.
    priority = Column(Text, nullable=False)
    # The priority you chose (Priority view, change 011). Analysis never
    # touches it; when set, it is the task's priority everywhere.
    user_priority = Column(Text, nullable=True)
    timing_text = Column(Text, nullable=True)
    ai_timing_text = Column(Text, nullable=True)
    timing_confirmed = Column(Integer, nullable=False, default=0)
    due_on = Column(Text, nullable=True)
    due_time = Column(Text, nullable=True)
    due_confidence = Column(Text, nullable=True)
    snoozed_until = Column(Text, nullable=True)
    reminder_at = Column(Text, nullable=True)
    # Set when the user edits text/priority; re-analysis then leaves them alone.
    user_edited = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(Text, nullable=False)
    dedup_key = Column(Text, nullable=False)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    # When it was completed (None while open or dismissed); change 011.
    completed_at = Column(Text, nullable=True)
    # A task for some day (change 018): no date, off the calendar and lists.
    someday = Column(Integer, nullable=False, default=0, server_default="0")
    someday_since = Column(Text, nullable=True)
    # A guessed date ("this weekend", "Friday") waiting for your OK; it stays
    # off due_on, so off the calendar and reminders, until you confirm it.
    # due_confidence says where the date stands: from_note, suggested or
    # user_confirmed (change 012).
    suggested_due_on = Column(Text, nullable=True)
    suggested_due_time = Column(Text, nullable=True)
    # Set when you edit the note of a task whose date you confirmed: the next
    # analysis may move the date to what the new text says, and asks you to
    # confirm it again (change 012). Without an edit a confirmed date stays.
    date_recheck = Column(Integer, nullable=False, default=0, server_default="0")


class CalendarActionReceiptRecord(Base):
    __tablename__ = "calendar_action_receipts"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Text, nullable=False)
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    payload_json = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)


class NotificationPreferenceRecord(Base):
    __tablename__ = "notification_preferences"

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled = Column(Integer, nullable=False, default=0, server_default="0")
    daily_digest_time = Column(
        Text, nullable=False, default="08:00", server_default="08:00"
    )
    timezone = Column(Text, nullable=False, default="UTC", server_default="UTC")
    include_unscheduled_prompt = Column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at = Column(Text, nullable=False)


class PushSubscriptionRecord(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_push_subscriptions_endpoint"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint = Column(Text, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class NotificationDeliveryRecord(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_notification_deliveries_idempotency_key",
        ),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind = Column(Text, nullable=False)
    local_date = Column(Text, nullable=False)
    idempotency_key = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    delivered_at = Column(Text, nullable=True)
    last_error = Column(Text, nullable=True)


class TaskDateChangeRecord(Base):
    """One change to a task's date: shown as "Updates" on its note (change 012)."""

    __tablename__ = "task_date_changes"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('set', 'postponed', 'moved_earlier', 'confirmed', 'note_edit')",
            name="ck_task_date_changes_kind",
        ),
        Index("ix_task_date_changes_item", "owner_user_id", "item_id"),
        Index("ix_task_date_changes_task", "task_id"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    # No foreign key: the history outlives a task that analysis replaces.
    task_id = Column(Integer, nullable=False)
    item_id = Column(Integer, nullable=True)
    task_text = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    from_due_on = Column(Text, nullable=True)
    from_due_time = Column(Text, nullable=True)
    to_due_on = Column(Text, nullable=True)
    to_due_time = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)


class TaskSourceItemRecord(Base):
    __tablename__ = "task_source_items"

    task_id = Column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    item_id = Column(
        Integer,
        ForeignKey("inbox_items.id", ondelete="CASCADE"),
        primary_key=True,
    )


class MemoryFactRecord(Base):
    """Something Life Inbox learned about you (change 016)."""

    __tablename__ = "memory_facts"
    __table_args__ = (
        CheckConstraint("kind IN ('long_term', 'short_term', 'example')", name="ck_memory_facts_kind"),
        CheckConstraint("status IN ('suggested', 'confirmed', 'expired', 'deleted')", name="ck_memory_facts_status"),
        CheckConstraint(
            "source_kind IN ('your_words', 'correction', 'needs_you', 'scout', 'onboarding', 'weekly_review', 'you')",
            name="ck_memory_facts_source_kind",
        ),
        UniqueConstraint("owner_user_id", "text_key", name="uq_memory_facts_text"),
        Index("ix_memory_facts_owner_status", "owner_user_id", "status"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bot_key = Column(Text, nullable=True)  # None: across areas (Captain)
    kind = Column(Text, nullable=False)
    text = Column(Text, nullable=False)
    text_key = Column(Text, nullable=False)
    source_item_ids = Column(Text, nullable=True)  # JSON list
    source_kind = Column(Text, nullable=False)
    status = Column(Text, nullable=False)
    times_seen = Column(Integer, nullable=False, default=1, server_default="1")
    valid_until = Column(Text, nullable=True)
    core_profile = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class UserSettingsRecord(Base):
    """Per-user settings (changes 016, 018, 020, 024, 025)."""

    __tablename__ = "user_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    health_memory_consent = Column(Integer, nullable=False, default=0, server_default="0")
    ai_processing = Column(Integer, nullable=False, default=1, server_default="1")
    catchup_day = Column(Text, nullable=False, default="sun", server_default="sun")
    catchup_time = Column(Text, nullable=False, default="19:00", server_default="19:00")
    last_seen_at = Column(Text, nullable=True)
    last_catchup_at = Column(Text, nullable=True)
    last_weekly_review_at = Column(Text, nullable=True)
    onboarding_done = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)
    # Days you were away when you came back (7+), until the catch-up is done (018).
    away_days = Column(Integer, nullable=True)


class TopicProposalRecord(Base):
    """A topic the weekly review suggests, waiting for you (change 020)."""

    __tablename__ = "topic_proposals"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'created', 'declined', 'never')", name="ck_topic_proposals_status"),
        Index("ix_topic_proposals_owner_status", "owner_user_id", "status"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bot_key = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    parent_topic_id = Column(Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    item_ids = Column(Text, nullable=False)
    signature = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="pending", server_default="pending")
    topic_id = Column(Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class BotSummaryRecord(Base):
    """An area's summary, rewritten only when the area changes (change 020)."""

    __tablename__ = "bot_summaries"

    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    bot_key = Column(Text, primary_key=True)
    summary = Column(Text, nullable=False)
    data_key = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)


class GreetingRecord(Base):
    """Captain's AI greeting, one per user per day (change 020, decision N)."""

    __tablename__ = "greetings"

    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    day = Column(Text, primary_key=True)
    text = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)


class TaskEventRecord(Base):
    """What happened to a task and who did it (change 018)."""

    __tablename__ = "task_events"
    __table_args__ = (
        CheckConstraint("kind IN ('done', 'rescheduled', 'dropped', 'someday', 'kept', 'reopened')",
                        name="ck_task_events_kind"),
        CheckConstraint("by IN ('you', 'scout')", name="ck_task_events_by"),
        Index("ix_task_events_owner_task", "owner_user_id", "task_id"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    kind = Column(Text, nullable=False)
    by = Column(Text, nullable=False)
    reason = Column(Text, nullable=True)
    from_due_on = Column(Text, nullable=True)
    to_due_on = Column(Text, nullable=True)
    created_at = Column(Text, nullable=False)


class PlanUpdateRecord(Base):
    """A note that changes a plan you already have, waiting for your Yes/No (017)."""

    __tablename__ = "plan_updates"
    __table_args__ = (
        CheckConstraint("status IN ('waiting', 'applied', 'declined')", name="ck_plan_updates_status"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("inbox_items.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(Integer, nullable=False)
    task_text = Column(Text, nullable=False)
    new_task_text = Column(Text, nullable=False)
    new_timing_text = Column(Text, nullable=True)
    new_due_on = Column(Text, nullable=True)
    new_due_time = Column(Text, nullable=True)
    status = Column(Text, nullable=False, default="waiting", server_default="waiting")
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class TaskIdeaRecord(Base):
    """An action found in your words that you didn't commit to (change 014a):
    a tentative plan Captain asks about, or a someday idea kept with its note.
    Not a task: never on the calendar, reminders or Priority."""

    __tablename__ = "task_ideas"
    __table_args__ = (
        CheckConstraint("intent IN ('tentative', 'someday')", name="ck_task_ideas_intent"),
        CheckConstraint("status IN ('waiting', 'added', 'dismissed')", name="ck_task_ideas_status"),
        Index("ix_task_ideas_owner_item", "owner_user_id", "item_id"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("inbox_items.id", ondelete="CASCADE"), nullable=False)
    text = Column(Text, nullable=False)
    timing_text = Column(Text, nullable=True)
    intent = Column(Text, nullable=False)
    status = Column(Text, nullable=False, default="waiting", server_default="waiting")
    task_id = Column(Integer, nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=False)


class CaptainAnswerRecord(Base):
    """Your answer to one of Captain's "Needs you" cards (change 013). One row
    per card key, so an answered card ("Not now" too) doesn't come back."""

    __tablename__ = "captain_answers"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "card_key", name="uq_captain_answers_card"),
        Index("ix_captain_answers_owner_item", "owner_user_id", "item_id"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    card_key = Column(Text, nullable=False)
    kind = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    # JSON: what the card asked and what you chose (memory examples, change 016).
    detail = Column(Text, nullable=True)
    # No foreign keys: the answer outlives a note, task or topic you delete.
    item_id = Column(Integer, nullable=True)
    task_id = Column(Integer, nullable=True)
    topic_id = Column(Integer, nullable=True)
    created_at = Column(Text, nullable=False)


AI_CALL_OUTCOMES = ("ok", "invalid", "error", "too_large")


class AiCallRecord(Base):
    """One request to the AI provider: sizes and outcome, never the text sent."""

    __tablename__ = "ai_calls"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('ok', 'invalid', 'error', 'too_large')",
            name="ck_ai_calls_outcome",
        ),
        Index("ix_ai_calls_owner_created", "owner_user_id", "created_at"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    action = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    outcome = Column(Text, nullable=False)
    attempt = Column(Integer, nullable=False, default=1, server_default="1")
    status_code = Column(Integer, nullable=True)
    # Characters for text requests, bytes for audio.
    input_size = Column(Integer, nullable=False, default=0, server_default="0")
    output_size = Column(Integer, nullable=False, default=0, server_default="0")
    duration_ms = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(Text, nullable=False)


# The 15 defaults of the five life areas (app/bots.py), plus the v1 catch-all.
# The catch-all belongs to no area and stays until change 014 re-sorts its
# notes, because v1 filing still falls back to it. Migration 0018 moves
# existing accounts onto these. Descriptions help the AI and the offline
# matcher decide which topic a note belongs to.
DEFAULT_TOPIC_NAMES = tuple(bots.DEFAULT_TOPIC_BOT)  # no catch-all for new accounts (change 014)
DEFAULT_TOPIC_DESCRIPTIONS = {
    **bots.DEFAULT_TOPIC_DESCRIPTIONS,
    bots.LEGACY_CATCH_ALL: bots.LEGACY_CATCH_ALL_DESCRIPTION,
}
CATCH_ALL_TOPIC = bots.LEGACY_CATCH_ALL
ORIGIN_BUILT_IN = "built_in"
ORIGIN_USER = "user"
ORIGIN_AI = "ai"
AI_CREATED_TOPIC_DESCRIPTION = "Created from AI organization"


class TopicConflictError(ValueError):
    """A topic name or parent choice that breaks the topic rules."""


def set_current_owner_id(owner_user_id: Optional[int]) -> None:
    _current_owner_id.set(owner_user_id)


def get_current_owner_id() -> Optional[int]:
    return _current_owner_id.get()


def record_ai_call(
    *,
    owner_user_id: int,
    action: str,
    model: str,
    outcome: str,
    attempt: int = 1,
    status_code: Optional[int] = None,
    input_size: int = 0,
    output_size: int = 0,
    duration_ms: int = 0,
) -> None:
    """Log one AI request (see app/llm.py). Never pass prompt or answer text."""
    if outcome not in AI_CALL_OUTCOMES:
        raise ValueError(f"Unknown AI call outcome: {outcome}")
    with SessionLocal() as session:
        session.add(
            AiCallRecord(
                owner_user_id=owner_user_id,
                action=action[:40],
                model=model[:120],
                outcome=outcome,
                attempt=attempt,
                status_code=status_code,
                input_size=max(0, int(input_size)),
                output_size=max(0, int(output_size)),
                duration_ms=max(0, int(duration_ms)),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        session.commit()


def list_ai_calls(limit: int = 200) -> list[dict]:
    """The signed-in user's most recent AI requests, newest first."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        rows = session.scalars(
            select(AiCallRecord)
            .where(AiCallRecord.owner_user_id == owner_id)
            .order_by(AiCallRecord.id.desc())
            .limit(limit)
        ).all()
        return [
            {
                "id": row.id,
                "action": row.action,
                "model": row.model,
                "outcome": row.outcome,
                "attempt": row.attempt,
                "status_code": row.status_code,
                "input_size": row.input_size,
                "output_size": row.output_size,
                "duration_ms": row.duration_ms,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def _user_to_dict(user: UserRecord) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "auth_provider": user.auth_provider,
        "created_at": user.created_at,
    }


def get_user_by_id(user_id: int) -> Optional[dict]:
    with SessionLocal() as session:
        user = session.get(UserRecord, user_id)
        return _user_to_dict(user) if user else None


def get_user_by_email(email: str) -> Optional[dict]:
    with SessionLocal() as session:
        user = session.scalar(
            select(UserRecord).where(UserRecord.email == email.strip().lower())
        )
        return _user_to_dict(user) if user else None


def ensure_user(
    *,
    email: str,
    display_name: str,
    auth_provider: str,
) -> dict:
    cleaned = email.strip().lower()
    with SessionLocal() as session:
        user = session.scalar(
            select(UserRecord).where(UserRecord.email == cleaned)
        )
        if user is None:
            user = UserRecord(
                email=cleaned,
                display_name=display_name.strip() or cleaned,
                auth_provider=auth_provider,
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            session.add(user)
            session.commit()
        return _user_to_dict(user)


class EmailAlreadyRegisteredError(ValueError):
    pass


def _credentials_to_dict(user: UserRecord) -> dict:
    return {
        **_user_to_dict(user),
        "password_hash": user.password_hash,
        "status": user.status,
        "failed_password_attempts": user.failed_password_attempts or 0,
        "locked_until": user.locked_until,
    }


def get_user_credentials_by_email(email: str) -> Optional[dict]:
    """Includes the password hash. Never return this dict to a client."""
    with SessionLocal() as session:
        user = session.scalar(
            select(UserRecord).where(UserRecord.email == email.strip().lower())
        )
        return _credentials_to_dict(user) if user else None


def get_user_credentials_by_id(user_id: int) -> Optional[dict]:
    """Includes the password hash. Never return this dict to a client."""
    with SessionLocal() as session:
        user = session.get(UserRecord, user_id)
        return _credentials_to_dict(user) if user else None


def create_password_user(
    *,
    email: str,
    display_name: str,
    password_hash: str,
    now_iso: str,
) -> dict:
    cleaned = email.strip().lower()
    with SessionLocal() as session:
        existing = session.scalar(
            select(UserRecord.id).where(UserRecord.email == cleaned)
        )
        if existing is not None:
            raise EmailAlreadyRegisteredError(cleaned)
        user = UserRecord(
            email=cleaned,
            display_name=display_name.strip() or cleaned.split("@", 1)[0],
            auth_provider="password",
            created_at=now_iso,
            password_hash=password_hash,
            password_changed_at=now_iso,
            status="active",
            failed_password_attempts=0,
            adult_confirmed_at=now_iso,
            terms_accepted_at=now_iso,
        )
        session.add(user)
        session.flush()
        ensure_default_topics(session, owner_user_id=user.id)
        session.commit()
        return _user_to_dict(user)


def get_user_credentials_by_google_sub(google_sub: str) -> Optional[dict]:
    """Includes status/password hash. Never return this dict to a client."""
    if not google_sub:
        return None
    with SessionLocal() as session:
        user = session.scalar(
            select(UserRecord).where(UserRecord.google_sub == google_sub)
        )
        return _credentials_to_dict(user) if user else None


def create_google_user(
    *,
    email: str,
    display_name: str,
    google_sub: str,
    now_iso: str,
) -> dict:
    """New account whose only way in is Google (no password hash)."""
    cleaned = email.strip().lower()
    with SessionLocal() as session:
        if session.scalar(
            select(UserRecord.id).where(UserRecord.email == cleaned)
        ) is not None:
            raise EmailAlreadyRegisteredError(cleaned)
        user = UserRecord(
            email=cleaned,
            display_name=display_name.strip() or cleaned.split("@", 1)[0],
            auth_provider="google",
            created_at=now_iso,
            password_hash=None,
            status="active",
            failed_password_attempts=0,
            email_verified_at=now_iso,
            adult_confirmed_at=now_iso,
            terms_accepted_at=now_iso,
            google_sub=google_sub,
        )
        session.add(user)
        session.flush()
        ensure_default_topics(session, owner_user_id=user.id)
        session.commit()
        return _user_to_dict(user)


def link_google_to_user(user_id: int, google_sub: str, now_iso: str) -> dict:
    """Attach a Google identity to an existing account.

    The old password is removed: sign-up never verified the email, so someone
    could have pre-registered it. Google has now proven who owns the address.
    """
    with SessionLocal() as session:
        user = session.get(UserRecord, user_id)
        if user is None:
            raise ValueError("User not found")
        user.google_sub = google_sub
        user.email_verified_at = user.email_verified_at or now_iso
        user.password_hash = None
        user.password_changed_at = now_iso
        user.failed_password_attempts = 0
        user.locked_until = None
        user.auth_provider = "google"
        session.commit()
        return _user_to_dict(user)


def record_password_failure(
    user_id: int, *, lock_after: int, locked_until_iso: str
) -> None:
    with SessionLocal() as session:
        user = session.get(UserRecord, user_id)
        if user is None:
            return
        user.failed_password_attempts = (user.failed_password_attempts or 0) + 1
        if user.failed_password_attempts >= lock_after:
            user.locked_until = locked_until_iso
            user.failed_password_attempts = 0
        session.commit()


def record_login_success(user_id: int, now_iso: str) -> None:
    with SessionLocal() as session:
        user = session.get(UserRecord, user_id)
        if user is None:
            return
        user.failed_password_attempts = 0
        user.locked_until = None
        user.last_login_at = now_iso
        session.commit()


def set_user_password_hash(user_id: int, password_hash: str, now_iso: str) -> None:
    with SessionLocal() as session:
        user = session.get(UserRecord, user_id)
        if user is None:
            return
        user.password_hash = password_hash
        user.password_changed_at = now_iso
        user.failed_password_attempts = 0
        user.locked_until = None
        session.commit()


def _auth_session_to_dict(record: AuthSessionRecord) -> dict:
    return {
        "id": record.id,
        "user_id": record.user_id,
        "auth_method": record.auth_method,
        "created_at": record.created_at,
        "last_seen_at": record.last_seen_at,
        "idle_expires_at": record.idle_expires_at,
        "absolute_expires_at": record.absolute_expires_at,
        "revoked_at": record.revoked_at,
        "device_label": record.device_label,
    }


def create_auth_session(
    *,
    user_id: int,
    token_hash: str,
    auth_method: str,
    now_iso: str,
    idle_expires_iso: str,
    absolute_expires_iso: str,
    device_label: Optional[str] = None,
) -> dict:
    with SessionLocal() as session:
        record = AuthSessionRecord(
            user_id=user_id,
            token_hash=token_hash,
            auth_method=auth_method,
            created_at=now_iso,
            last_seen_at=now_iso,
            idle_expires_at=idle_expires_iso,
            absolute_expires_at=absolute_expires_iso,
            device_label=device_label,
        )
        session.add(record)
        session.commit()
        return _auth_session_to_dict(record)


def get_auth_session_by_token_hash(token_hash: str) -> Optional[dict]:
    with SessionLocal() as session:
        record = session.scalar(
            select(AuthSessionRecord).where(
                AuthSessionRecord.token_hash == token_hash
            )
        )
        return _auth_session_to_dict(record) if record else None


def touch_auth_session(
    session_id: int, *, now_iso: str, idle_expires_iso: str
) -> None:
    with SessionLocal() as session:
        record = session.get(AuthSessionRecord, session_id)
        if record is None or record.revoked_at is not None:
            return
        record.last_seen_at = now_iso
        record.idle_expires_at = idle_expires_iso
        session.commit()


def revoke_auth_session(token_hash: str, *, now_iso: str, reason: str) -> bool:
    with SessionLocal() as session:
        record = session.scalar(
            select(AuthSessionRecord).where(
                AuthSessionRecord.token_hash == token_hash
            )
        )
        if record is None or record.revoked_at is not None:
            return False
        record.revoked_at = now_iso
        record.revoked_reason = reason
        session.commit()
        return True


def revoke_user_auth_sessions(
    user_id: int,
    *,
    now_iso: str,
    reason: str,
    keep_token_hash: Optional[str] = None,
) -> int:
    with SessionLocal() as session:
        statement = select(AuthSessionRecord).where(
            AuthSessionRecord.user_id == user_id,
            AuthSessionRecord.revoked_at.is_(None),
        )
        if keep_token_hash is not None:
            statement = statement.where(
                AuthSessionRecord.token_hash != keep_token_hash
            )
        records = session.scalars(statement).all()
        for record in records:
            record.revoked_at = now_iso
            record.revoked_reason = reason
        session.commit()
        return len(records)


def _otp_to_dict(record: OtpChallengeRecord) -> dict:
    return {
        "id": record.id,
        "purpose": record.purpose,
        "user_id": record.user_id,
        "code_hash": record.code_hash,
        "attempts": record.attempts,
        "max_attempts": record.max_attempts,
        "created_at": record.created_at,
        "expires_at": record.expires_at,
        "consumed_at": record.consumed_at,
    }


def create_otp_challenge(
    *,
    purpose: str,
    identifier_hash: str,
    user_id: Optional[int],
    code_hash: Optional[str],
    now_iso: str,
    expires_iso: str,
    max_attempts: int,
) -> dict:
    with SessionLocal() as session:
        record = OtpChallengeRecord(
            purpose=purpose,
            identifier_hash=identifier_hash,
            user_id=user_id,
            code_hash=code_hash,
            attempts=0,
            max_attempts=max_attempts,
            created_at=now_iso,
            expires_at=expires_iso,
        )
        session.add(record)
        session.commit()
        return _otp_to_dict(record)


def list_recent_otp_challenges(
    *, purpose: str, identifier_hash: str, since_iso: str
) -> list[dict]:
    """Newest first."""
    with SessionLocal() as session:
        records = session.scalars(
            select(OtpChallengeRecord)
            .where(
                OtpChallengeRecord.purpose == purpose,
                OtpChallengeRecord.identifier_hash == identifier_hash,
                OtpChallengeRecord.created_at >= since_iso,
            )
            .order_by(OtpChallengeRecord.id.desc())
        ).all()
        return [_otp_to_dict(record) for record in records]


def record_otp_failure(challenge_id: int) -> None:
    with SessionLocal() as session:
        record = session.get(OtpChallengeRecord, challenge_id)
        if record is not None:
            record.attempts = (record.attempts or 0) + 1
            session.commit()


def consume_otp_challenge(challenge_id: int, now_iso: str) -> bool:
    """Mark a code as used. Returns False if it was already used."""
    with SessionLocal() as session:
        record = session.get(OtpChallengeRecord, challenge_id)
        if record is None or record.consumed_at is not None:
            return False
        record.consumed_at = now_iso
        session.commit()
        return True


def require_owner_id() -> int:
    """Owner of the current request. Never falls back to a shared user."""
    owner = get_current_owner_id()
    if owner is None:
        raise NotAuthenticatedError("Authentication required.")
    return owner


def ensure_default_topics(session, owner_user_id: Optional[int] = None) -> None:
    owner = owner_user_id
    statement = select(func.count()).select_from(TopicRecord)
    if owner is not None:
        statement = statement.where(TopicRecord.owner_user_id == owner)
    count = session.scalar(statement) or 0
    if count:
        return
    now = datetime.now(timezone.utc).isoformat()
    for name in DEFAULT_TOPIC_NAMES:
        session.add(
            TopicRecord(
                name=name,
                description=DEFAULT_TOPIC_DESCRIPTIONS.get(name),
                owner_user_id=owner,
                created_at=now,
                updated_at=now,
                archived=0,
                bot_key=bots.DEFAULT_TOPIC_BOT.get(name),
                origin=ORIGIN_BUILT_IN,
            )
        )
    session.flush()
    # Built-in subtopics sit under their parent (Hobbies › Cooking).
    made = {
        topic.name: topic
        for topic in session.scalars(select(TopicRecord).where(TopicRecord.owner_user_id == owner)).all()
    }
    for child, parent in bots.DEFAULT_TOPIC_PARENT.items():
        if child in made and parent in made:
            made[child].parent_topic_id = made[parent].id
    session.flush()


class SchemaOutOfDateError(RuntimeError):
    pass


def ensure_schema_is_current() -> None:
    """Refuse to start against a database Alembic hasn't upgraded to head.

    Otherwise new code runs against old tables and fails on every request
    (e.g. sign-in errors with 500 because ``users.password_hash`` is missing).
    """
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    project_root = Path(__file__).resolve().parent.parent
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "migrations"))
    expected = set(ScriptDirectory.from_config(config).get_heads())
    with engine.connect() as connection:
        current = set(MigrationContext.configure(connection).get_current_heads())
    if current != expected:
        found = ", ".join(sorted(current)) or "none (empty database)"
        raise SchemaOutOfDateError(
            f"Database schema is out of date (found {found}; app needs "
            f"{', '.join(sorted(expected))}). Back up the database, then run: "
            "python -m alembic upgrade head"
        )


def init_db():
    """Prepare the DB connection.

    Alembic owns schema evolution. Table auto-creation is opt-in for isolated
    automated tests via LIFE_INBOX_AUTO_CREATE_TABLES=1.
    """
    if not AUTO_CREATE_TABLES:
        ensure_schema_is_current()
    if AUTO_CREATE_TABLES:
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as session:
            owner = ensure_user(
                email=DEFAULT_OWNER_EMAIL,
                display_name="Local Owner",
                auth_provider="local",
            )
            ensure_default_topics(session, owner_user_id=owner["id"])
            session.commit()


def _looks_secret(item: "InboxItemRecord") -> bool:
    from app.sensitive import looks_secret

    return any(looks_secret(value) for value in (item.raw_text, item.user_context, item.extracted_text))


def _secret_masked(item: "InboxItemRecord") -> Optional[dict]:
    """The note's text with secret values hidden, for the screen (change 016)."""
    if not _looks_secret(item):
        return None
    from app.sensitive import mask_secrets

    return {field: mask_secrets(getattr(item, field)) if getattr(item, field) else getattr(item, field)
            for field in ("title", "raw_text", "user_context", "extracted_text")}


def _parse_card(raw: Optional[str]) -> Optional[dict]:
    try:
        card = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return card if isinstance(card, dict) else None


def _item_to_dict(item: InboxItemRecord) -> dict:
    return {
        "id": item.id,
        "item_type": item.item_type,
        "title": item.title,
        "raw_text": item.raw_text,
        "source_url": item.source_url,
        "original_filename": item.original_filename,
        "mime_type": item.mime_type,
        "processing_status": item.processing_status,
        "error_message": item.error_message,
        "storage_path": item.storage_path,
        "extracted_text": item.extracted_text,
        "ai_description": item.ai_description,
        "user_context": item.user_context,
        "link_card": _parse_card(item.link_card),
        "source_summary": item.source_summary,
        "looks_secret": _looks_secret(item),
        "secret_masked": _secret_masked(item),
        "owner_user_id": item.owner_user_id,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def add_item_to_db(raw_text: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=TEXT_ITEM_TYPE,
            raw_text=raw_text,
            processing_status=READY_STATUS,
            owner_user_id=owner_id,
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def list_items_from_db(
    search: Optional[str] = None,
    item_type: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    processing_status: Optional[str] = None,
    limit: Optional[int] = 100,
    offset: int = 0,
    bot: Optional[str] = None,
    newest_first: bool = False,
    topic_id: Optional[int] = None,
) -> list[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        statement = select(InboxItemRecord).where(
            InboxItemRecord.owner_user_id == owner_id
        )
        if bot is not None:
            statement = statement.where(
                InboxItemRecord.id.in_(_bot_item_ids(owner_id, bot))
            )
        if topic_id is not None:
            statement = statement.where(
                InboxItemRecord.id.in_(_topic_item_ids(owner_id, topic_id))
            )

        if category or priority:
            statement = statement.join(
                ItemInsightRecord,
                ItemInsightRecord.item_id == InboxItemRecord.id,
            )

        search_text = (search or "").strip()
        if search_text:
            statement = statement.where(
                or_(
                    InboxItemRecord.raw_text.icontains(
                        search_text,
                        autoescape=True,
                    ),
                    InboxItemRecord.title.icontains(
                        search_text,
                        autoescape=True,
                    ),
                    InboxItemRecord.extracted_text.icontains(
                        search_text,
                        autoescape=True,
                    ),
                    InboxItemRecord.original_filename.icontains(
                        search_text,
                        autoescape=True,
                    ),
                )
            )
        if item_type:
            statement = statement.where(
                InboxItemRecord.item_type == item_type
            )
        if category:
            statement = statement.where(
                ItemInsightRecord.category == category
            )
        if priority:
            statement = statement.where(
                ItemInsightRecord.priority == priority
            )
        if processing_status:
            statement = statement.where(
                InboxItemRecord.processing_status == processing_status
            )

        statement = statement.order_by(
            InboxItemRecord.id.desc() if newest_first else InboxItemRecord.id.asc()
        ).offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        items = session.scalars(statement).all()
        return [_item_to_dict(item) for item in items]


def compute_inbox_fingerprint(session=None) -> str:
    """Stable hash of current inbox content used to detect stale analysis."""
    owner_id = require_owner_id()

    def _fingerprint(active_session) -> str:
        items = active_session.scalars(
            select(InboxItemRecord)
            .where(InboxItemRecord.owner_user_id == owner_id)
            .order_by(InboxItemRecord.id.asc())
        ).all()
        payload = [
            [
                item.id,
                item.item_type,
                item.raw_text or "",
                item.title or "",
                item.source_url or "",
                item.processing_status,
                item.updated_at or item.created_at,
            ]
            for item in items
        ]
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    if session is not None:
        return _fingerprint(session)
    with SessionLocal() as owned_session:
        return _fingerprint(owned_session)


def update_item_in_db(item_id: int, raw_text: str) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if (
            item is None
            or item.item_type not in (TEXT_ITEM_TYPE, VOICE_ITEM_TYPE)
            or item.owner_user_id != owner_id
        ):
            return None

        if raw_text != item.raw_text:
            _flag_dates_for_recheck(session, item.id)
        item.raw_text = raw_text
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def update_item_context(item_id: int, context: Optional[str]) -> Optional[dict]:
    """Your note on a saved source (a link, PDF, image or voice note), changed
    (change 023). Empty removes it. Its dates are re-read at the next filing."""
    owner_id = require_owner_id()
    cleaned = (context or "").strip()[:2000] or None
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.owner_user_id != owner_id or item.item_type == TEXT_ITEM_TYPE:
            return None
        if cleaned != item.user_context:
            _flag_dates_for_recheck(session, item.id)
        item.user_context = cleaned
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def _flag_dates_for_recheck(session, item_id: int) -> None:
    """You edited this note: its open tasks with a confirmed date get their
    date re-read from the new text at the next analysis (change 012)."""
    for task in session.scalars(
        select(TaskRecord)
        .join(TaskSourceItemRecord, TaskSourceItemRecord.task_id == TaskRecord.id)
        .where(
            TaskSourceItemRecord.item_id == item_id,
            TaskRecord.status == TASK_OPEN,
            TaskRecord.timing_confirmed == 1,
        )
    ).all():
        task.date_recheck = 1


def _remove_orphan_tasks(session, item_ids: list[int]) -> None:
    """Drop source links for deleted items and remove tasks with no sources."""
    if not item_ids:
        return

    affected_task_ids = session.scalars(
        select(TaskSourceItemRecord.task_id).where(
            TaskSourceItemRecord.item_id.in_(item_ids)
        )
    ).all()
    for link in session.scalars(
        select(TaskSourceItemRecord).where(
            TaskSourceItemRecord.item_id.in_(item_ids)
        )
    ).all():
        session.delete(link)
    session.flush()

    for task_id in sorted(set(affected_task_ids)):
        remaining = session.scalars(
            select(TaskSourceItemRecord.item_id).where(
                TaskSourceItemRecord.task_id == task_id
            )
        ).all()
        if remaining:
            task = session.get(TaskRecord, task_id)
            if task is not None:
                task.dedup_key = _task_dedup_key(list(remaining), task.text)
            continue
        task = session.get(TaskRecord, task_id)
        if task is not None:
            session.delete(task)


def delete_item_from_db(item_id: int) -> bool:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.owner_user_id != owner_id:
            return False

        insight = session.get(ItemInsightRecord, item_id)
        if insight is not None:
            session.delete(insight)
        _remove_orphan_tasks(session, [item_id])
        storage_path = item.storage_path
        session.delete(item)
        session.commit()
        delete_stored_file(storage_path)
        return True


def complete_item_in_db(item_id: int) -> dict:
    owner_id = require_owner_id()
    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.owner_user_id != owner_id:
            raise ValueError(f"Item {item_id} not found")

        tasks = session.scalars(
            select(TaskRecord)
            .join(TaskSourceItemRecord)
            .where(TaskSourceItemRecord.item_id == item_id)
        ).all()

        if tasks:
            for task in tasks:
                if task.status != TASK_COMPLETED:
                    task.status = TASK_COMPLETED
                    task.updated_at = completed_at
                    task.completed_at = completed_at
        else:
            task_title = item.title or (
                (item.raw_text or item.extracted_text or "Note").strip().split("\n")[0][:60]
            )
            clean_title = task_title or "Note"
            dedup_key = _task_dedup_key([item_id], clean_title)
            task = TaskRecord(
                text=clean_title,
                priority="Medium",
                status=TASK_COMPLETED,
                dedup_key=dedup_key,
                owner_user_id=owner_id,
                created_at=completed_at,
                updated_at=completed_at,
                completed_at=completed_at,
            )
            session.add(task)
            session.flush()
            session.add(TaskSourceItemRecord(task_id=task.id, item_id=item_id))

        session.commit()
        return _item_to_dict(item)


def _item_to_note(item: dict) -> dict:
    return {
        "id": item["id"],
        "text": item["raw_text"],
        "created_at": item["created_at"],
    }


def add_note_to_db(text: str) -> dict:
    return _item_to_note(add_item_to_db(text))


def list_notes_from_db(exclude_completed: bool = False) -> list[dict]:
    """Analyzable ready items exposed in the legacy note shape for the organizer."""
    completed_ids = set()
    if exclude_completed:
        owner_id = require_owner_id()
        with SessionLocal() as session:
            completed_ids = set(
                session.scalars(
                    select(TaskSourceItemRecord.item_id)
                    .join(TaskRecord)
                    .where(
                        TaskRecord.status == TASK_COMPLETED,
                        TaskRecord.owner_user_id == owner_id,
                    )
                ).all()
            )
    notes = []
    for item in list_items_from_db(limit=None, offset=0):
        if exclude_completed and item["id"] in completed_ids:
            continue
        if item["item_type"] not in ANALYZABLE_TYPES:
            continue
        if item["processing_status"] not in ANALYZABLE_STATUSES:
            continue
        note = _note_from_item(item)
        if note is not None:
            notes.append(note)
    return notes


def _note_from_item(item: dict) -> Optional[dict]:
    """Organizer input: source text plus the user's own context, kept apart."""
    card = item.get("link_card") if isinstance(item.get("link_card"), dict) else None
    # A link's source is its card (change 015): the facts code read, cut to 1,500 characters.
    text = (card or {}).get("text") or item.get("extracted_text") or item.get("raw_text") or ""
    if item.get("source_summary"):
        # A long PDF's one-time summary (022) comes first, so the cut keeps it.
        text = f"Summary (AI): {item['source_summary']}\n\n{text}"
    context = (item.get("user_context") or "").strip()
    if not text and not context:
        return None
    note = {"id": item["id"], "text": text, "created_at": item["created_at"]}
    if context:
        note["context"] = context
    if item.get("item_type") and item["item_type"] != TEXT_ITEM_TYPE:
        note["source"] = item["item_type"]
        if item.get("title"):
            note["source_title"] = item["title"]
    return note


def get_note_from_db(item_id: int) -> Optional[dict]:
    item = get_item_from_db(item_id)
    if (
        not item
        or item["item_type"] not in ANALYZABLE_TYPES
        or item["processing_status"] not in ANALYZABLE_STATUSES
    ):
        return None
    return _note_from_item(item)


def update_note_in_db(note_id: int, text: str) -> Optional[dict]:
    item = update_item_in_db(note_id, text)
    return _item_to_note(item) if item is not None else None


def delete_note_from_db(note_id: int) -> bool:
    return delete_item_from_db(note_id)


def start_analysis_run() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        run = AnalysisRunRecord(
            started_at=started_at,
            status=ANALYSIS_RUNNING,
            mode="pending",
            owner_user_id=owner_id,
        )
        session.add(run)
        session.commit()
        return run.id


_QUOTE_CHARS = "\"'\u201c\u201d\u2018\u2019`"
# What an AI sometimes appends after a real topic name, e.g.
# "Ideas: Product, business..." or "Health (subtopic ...)".
_TOPIC_SUFFIX_SEPARATORS = (":", " -", " \u2013", " \u2014", " (", " |")


def _clean_bucket_name(name: str) -> str:
    return (name or "").strip().strip(_QUOTE_CHARS).strip().rstrip(".").strip()


def _resolve_existing_topic(session, owner_id: int, name: str) -> Optional[TopicRecord]:
    """Map an AI bucket name onto one of the owner's existing topics.

    Exact (case-insensitive) match first; otherwise a known topic name
    followed by extra text such as ": description" (longest name wins).
    """
    cleaned = _clean_bucket_name(name).lower()
    if not cleaned:
        return None
    topics = session.scalars(
        select(TopicRecord).where(
            TopicRecord.owner_user_id == owner_id,
            TopicRecord.archived == 0,
        )
    ).all()
    for topic in topics:
        if topic.name.strip().lower() == cleaned:
            return topic
    for topic in sorted(topics, key=lambda t: len(t.name), reverse=True):
        prefix = topic.name.strip().lower()
        if cleaned.startswith(prefix) and any(
            cleaned[len(prefix):].startswith(sep) for sep in _TOPIC_SUFFIX_SEPARATORS
        ):
            return topic
    return None


def _normalize_buckets_to_topics(session, owner_id: int, buckets: list[dict]) -> list[dict]:
    """Rename AI buckets to the matching existing topic and merge duplicates."""
    merged: dict[str, dict] = {}
    for bucket in buckets:
        topic = _resolve_existing_topic(session, owner_id, bucket.get("name", ""))
        name = topic.name if topic else (_clean_bucket_name(bucket.get("name", "")) or CATCH_ALL_TOPIC)
        key = name.lower()
        if key not in merged:
            merged[key] = {**bucket, "name": name, "notes": list(bucket.get("notes") or [])}
        else:
            merged[key]["notes"].extend(bucket.get("notes") or [])
    return list(merged.values())


def _topic_id_by_name(session, name: str) -> Optional[int]:
    owner_id = require_owner_id()
    ensure_default_topics(session, owner_user_id=owner_id)
    topic = _resolve_existing_topic(session, owner_id, name)
    if topic is not None:
        return topic.id
    name = _clean_bucket_name(name) or CATCH_ALL_TOPIC
    now = datetime.now(timezone.utc).isoformat()
    is_catch_all = name.lower() == CATCH_ALL_TOPIC.lower()
    topic = TopicRecord(
        name=CATCH_ALL_TOPIC if is_catch_all else name,
        description=(
            DEFAULT_TOPIC_DESCRIPTIONS[CATCH_ALL_TOPIC]
            if is_catch_all
            else AI_CREATED_TOPIC_DESCRIPTION
        ),
        owner_user_id=owner_id,
        created_at=now,
        updated_at=now,
        archived=0,
        bot_key=None if is_catch_all else bots.bot_for_text(name),
        origin=ORIGIN_BUILT_IN if is_catch_all else ORIGIN_AI,
    )
    session.add(topic)
    session.flush()
    return topic.id


def _normalize_task_text(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def merge_analysis_into_cumulative(
    previous_json: Optional[str],
    single_result: dict,
    completed_item_ids: set[int],
) -> dict:
    if not previous_json:
        return single_result
    try:
        prev = json.loads(previous_json)
        if not isinstance(prev, dict) or "buckets" not in prev:
            return single_result
    except Exception:
        return single_result

    new_note_ids = {
        n["id"]
        for b in single_result.get("buckets", [])
        for n in b.get("notes", [])
    }

    merged_buckets: dict[str, list[dict]] = {}
    for b in prev.get("buckets", []):
        name = b["name"]
        active_notes = [
            n for n in b.get("notes", [])
            if n["id"] not in new_note_ids and n["id"] not in completed_item_ids
        ]
        if active_notes:
            merged_buckets[name] = active_notes

    for b in single_result.get("buckets", []):
        name = b["name"]
        for n in b.get("notes", []):
            if n["id"] not in completed_item_ids:
                merged_buckets.setdefault(name, []).append(n)

    merged_pv: dict[str, list[dict]] = {"High": [], "Medium": [], "Low": []}
    prev_pv = prev.get("priority_view", {})
    if isinstance(prev_pv, dict):
        for level in ("High", "Medium", "Low"):
            for n in prev_pv.get(level, []):
                if n["id"] not in new_note_ids and n["id"] not in completed_item_ids:
                    merged_pv[level].append(n)
    single_pv = single_result.get("priority_view", {})
    if isinstance(single_pv, dict):
        for level in ("High", "Medium", "Low"):
            for n in single_pv.get(level, []):
                if n["id"] not in completed_item_ids:
                    merged_pv[level].append(n)

    merged_todos = []
    for t in prev.get("todos", []):
        sources = set(t.get("source_note_ids", []))
        if not (sources & new_note_ids) and not (sources and sources <= completed_item_ids):
            merged_todos.append(t)
    for t in single_result.get("todos", []):
        sources = set(t.get("source_note_ids", []))
        if not (sources and sources <= completed_item_ids):
            merged_todos.append(t)

    return {
        "buckets": [{"name": k, "notes": v} for k, v in merged_buckets.items()],
        "todos": merged_todos,
        "priority_view": merged_pv,
        "mode": single_result.get("mode", "nvidia_nim"),
    }


# Filing v2 puts notes waiting for your pick in this bucket: no topic is made
# or set for it (change 014, rule R6).
PENDING_BUCKET = "Needs you"
FILED_BY = ("ai", "offline", "you")


def complete_analysis_run(
    run_id: int, result: dict, merge_single: bool = False, filing: Optional[dict] = None
) -> dict:
    """Save an analysis. `filing` (change 014) carries filing v2's details per
    note id: rule, confidence, choices, filed_by, pending, summary, action,
    cleaned transcript; and "task_dates", the AI's suggested ISO dates keyed by
    note id and task text."""
    completed_at = datetime.now(timezone.utc).isoformat()
    filing = filing or {}
    notes_meta = filing.get("notes") or {}
    with SessionLocal() as session:
        run = session.get(AnalysisRunRecord, run_id)
        if run is None or run.status != ANALYSIS_RUNNING:
            raise ValueError("Analysis run is not available for completion")

        ensure_default_topics(session, owner_user_id=require_owner_id())
        # Map names like "Ideas: Product, business..." back onto "Ideas" so
        # no near-duplicate topics are created, and the saved view matches.
        pending_buckets = [b for b in result["buckets"] if notes_meta and b["name"] == PENDING_BUCKET]
        result["buckets"] = _normalize_buckets_to_topics(
            session, require_owner_id(), [b for b in result["buckets"] if b not in pending_buckets]
        ) + pending_buckets

        for bucket in result["buckets"]:
            pending = bucket in pending_buckets
            topic_id = None if pending else _topic_id_by_name(session, bucket["name"])
            for analyzed_item in bucket["notes"]:
                item_id = analyzed_item["id"]
                if session.get(InboxItemRecord, item_id) is None:
                    raise ValueError(
                        f"Analysis references missing item {item_id}"
                    )
                insight = session.get(ItemInsightRecord, item_id)
                if insight is None:
                    insight = ItemInsightRecord(
                        item_id=item_id,
                        needs_review=0,
                    )
                    session.add(insight)
                insight.analysis_run_id = run_id
                # AI fields always refresh; user overrides are preserved.
                insight.category = bucket["name"]
                insight.concise_title = analyzed_item["title"]
                insight.priority = analyzed_item["priority"]
                insight.topic_id = topic_id
                tags = analyzed_item.get("tags") or []
                insight.tags_json = json.dumps(tags, ensure_ascii=False)
                insight.rationale = analyzed_item.get("rationale") or (
                    f"Grouped under “{bucket['name']}” based on the note content."
                )
                insight.needs_review = 0
                insight.updated_at = completed_at
                meta = notes_meta.get(item_id)
                if meta is not None:
                    _apply_filing_meta(insight, meta, pending)
                item = session.get(InboxItemRecord, item_id)
                if item is not None and insight.user_title is None:
                    item.title = analyzed_item["title"]

        owner_id = require_owner_id()
        if merge_single:
            analyzed_item_ids = {
                n["id"]
                for b in result.get("buckets", [])
                for n in b.get("notes", [])
            }
            if not analyzed_item_ids:
                analyzed_item_ids = {
                    item_id
                    for todo in result.get("todos", [])
                    for item_id in todo.get("source_note_ids", [])
                }
        else:
            analyzed_item_ids = set(
                session.scalars(
                    select(InboxItemRecord.id).where(
                        InboxItemRecord.owner_user_id == owner_id
                    )
                ).all()
            )

        existing_tasks = session.scalars(
            select(TaskRecord).where(TaskRecord.owner_user_id == owner_id)
        ).all()
        task_sources = {
            t.id: set(
                session.scalars(
                    select(TaskSourceItemRecord.item_id).where(
                        TaskSourceItemRecord.task_id == t.id
                    )
                ).all()
            )
            for t in existing_tasks
        }
        matched_task_ids = set()

        for todo in result["todos"]:
            source_item_ids = sorted(set(todo["source_note_ids"]))
            if not source_item_ids:
                continue
            for item_id in source_item_ids:
                if session.get(InboxItemRecord, item_id) is None:
                    raise ValueError(
                        f"Task references missing item {item_id}"
                    )

            dedup_key = _task_dedup_key(source_item_ids, todo["task"])
            target_norm = _normalize_task_text(todo["task"])
            target_words = set(target_norm.split())

            task = next(
                (
                    t
                    for t in existing_tasks
                    if t.id not in matched_task_ids and t.dedup_key == dedup_key
                ),
                None,
            )

            if task is None:
                candidates = [
                    t
                    for t in existing_tasks
                    if t.id not in matched_task_ids
                    and task_sources.get(t.id) == set(source_item_ids)
                ]

                for candidate in candidates:
                    if _normalize_task_text(candidate.text) == target_norm:
                        task = candidate
                        break

                if task is None:
                    for candidate in candidates:
                        candidate_norm = _normalize_task_text(candidate.text)
                        candidate_words = set(candidate_norm.split())
                        if (
                            target_norm
                            and candidate_norm
                            and (
                                target_norm in candidate_norm
                                or candidate_norm in target_norm
                            )
                        ):
                            task = candidate
                            break
                        if target_words and candidate_words:
                            overlap = len(target_words & candidate_words)
                            containment = overlap / min(
                                len(target_words), len(candidate_words)
                            )
                            jaccard = overlap / len(
                                target_words | candidate_words
                            )
                            if containment >= 0.5 or jaccard >= 0.4:
                                task = candidate
                                break

                if task is None and set(source_item_ids).issubset(analyzed_item_ids):
                    open_candidates = [
                        c for c in candidates if c.status == TASK_OPEN
                    ]
                    todos_for_source = [
                        t
                        for t in result["todos"]
                        if sorted(set(t.get("source_note_ids") or []))
                        == source_item_ids
                    ]
                    if len(open_candidates) == 1 and len(todos_for_source) == 1:
                        task = open_candidates[0]

            from app.attention.dates import (
                normalize_time_of_day,
                parse_timing_phrase,
            )

            written_on = _written_day(session, source_item_ids)
            ai_date = (filing.get("task_dates") or {}).get(
                (source_item_ids[0], _normalize_task_text(todo["task"]))
            )
            if task is None:
                task = TaskRecord(
                    text=todo["task"],
                    priority=todo["priority"],
                    ai_timing_text=todo["when"],
                    timing_confirmed=0,
                    status=TASK_OPEN,
                    dedup_key=dedup_key,
                    owner_user_id=owner_id,
                    created_at=completed_at,
                    updated_at=completed_at,
                )
                _apply_timing(task, todo.get("when"), written_on, ai_date)
                session.add(task)
                session.flush()
                for item_id in source_item_ids:
                    session.add(
                        TaskSourceItemRecord(
                            task_id=task.id,
                            item_id=item_id,
                        )
                    )
            else:
                if not task.user_edited:
                    # Text you edited yourself stays yours (your teammates' fix).
                    task.text = todo["task"]
                task.priority = todo["priority"]  # the AI's; yours is user_priority
                task.ai_timing_text = todo["when"]
                if not task.timing_confirmed:
                    _apply_timing(task, todo.get("when"), written_on, ai_date)
                elif task.date_recheck:
                    # You edited the note: if its new words give another date,
                    # move the task there and ask you to confirm it again.
                    parsed_timing = parse_timing_phrase(todo.get("when"), reference=written_on)
                    new_on = parsed_timing.normalized_iso
                    new_time = normalize_time_of_day(todo.get("when"))
                    if new_on and (new_on != task.due_on or (new_time and new_time != task.due_time)):
                        _record_date_change(
                            session, task, "note_edit", new_on, new_time, completed_at,
                            item_id=source_item_ids[0] if source_item_ids else None,
                        )
                        _apply_timing(task, todo.get("when"), written_on)
                        task.timing_confirmed = 0
                task.date_recheck = 0
                task.dedup_key = dedup_key
                task.updated_at = completed_at
                linked = task_sources.get(task.id, set())
                for item_id in source_item_ids:
                    if item_id not in linked:
                        session.add(
                            TaskSourceItemRecord(
                                task_id=task.id,
                                item_id=item_id,
                            )
                        )
            matched_task_ids.add(task.id)

        _save_ideas(session, owner_id, filing.get("ideas"), set(notes_meta), completed_at)
        _save_plan_updates(session, owner_id, filing.get("plan_updates"), completed_at)
        for item_id, facts in (filing.get("facts") or {}).items():
            insight = session.get(ItemInsightRecord, item_id)
            topic = session.get(TopicRecord, insight.topic_id) if insight is not None and insight.topic_id else None
            for fact in facts or []:
                _remember_in(session, owner_id, fact, kind="long_term", source_kind="your_words",
                             bot_key=topic.bot_key if topic else None, item_ids=[item_id], status="suggested")

        for existing in existing_tasks:
            sources = task_sources.get(existing.id)
            if (
                existing.status == TASK_OPEN
                and existing.id not in matched_task_ids
                and sources
                and sources.issubset(analyzed_item_ids)
            ):
                for link in session.scalars(
                    select(TaskSourceItemRecord).where(
                        TaskSourceItemRecord.task_id == existing.id
                    )
                ).all():
                    session.delete(link)
                session.delete(existing)

        # Refresh deterministic relations for current inbox text.
        # Only this owner's items/relations: never read or delete another
        # user's data while refreshing relations.
        items = [
            _item_to_dict(item)
            for item in session.scalars(
                select(InboxItemRecord).where(
                    InboxItemRecord.owner_user_id == owner_id
                )
            ).all()
        ]
        owner_item_ids = [item["id"] for item in items]
        if owner_item_ids:
            for relation in session.scalars(
                select(ItemRelationRecord).where(
                    ItemRelationRecord.item_id_a.in_(owner_item_ids)
                )
            ).all():
                if not relation.dismissed:
                    session.delete(relation)
        session.flush()
        for relation in find_item_relations(items):
            existing = session.scalars(
                select(ItemRelationRecord).where(
                    ItemRelationRecord.item_id_a == relation["item_id_a"],
                    ItemRelationRecord.item_id_b == relation["item_id_b"],
                    ItemRelationRecord.relation_type
                    == relation["relation_type"],
                )
            ).first()
            if existing is not None:
                if existing.dismissed:
                    continue
                existing.score = relation["score"]
                continue
            session.add(
                ItemRelationRecord(
                    item_id_a=relation["item_id_a"],
                    item_id_b=relation["item_id_b"],
                    relation_type=relation["relation_type"],
                    score=relation["score"],
                    created_at=completed_at,
                    dismissed=0,
                )
            )

        completed_item_ids = set(
            session.scalars(
                select(TaskSourceItemRecord.item_id)
                .join(TaskRecord)
                .where(
                    TaskRecord.status == TASK_COMPLETED,
                    TaskRecord.owner_user_id == owner_id,
                )
            ).all()
        )
        persisted = result
        if merge_single:
            prev_run = session.scalars(
                select(AnalysisRunRecord)
                .where(
                    AnalysisRunRecord.status == ANALYSIS_SUCCEEDED,
                    AnalysisRunRecord.id != run_id,
                    AnalysisRunRecord.owner_user_id == require_owner_id(),
                )
                .order_by(
                    AnalysisRunRecord.completed_at.desc(),
                    AnalysisRunRecord.id.desc(),
                )
                .limit(1)
            ).first()
            if prev_run and prev_run.result_json:
                persisted = merge_analysis_into_cumulative(
                    prev_run.result_json,
                    result,
                    completed_item_ids,
                )
        else:
            filtered_buckets = []
            for b in persisted.get("buckets", []):
                active_notes = [
                    n for n in b.get("notes", [])
                    if n.get("id") not in completed_item_ids
                ]
                if active_notes:
                    filtered_buckets.append({**b, "notes": active_notes})
            persisted["buckets"] = filtered_buckets
            pv = persisted.get("priority_view", {})
            if isinstance(pv, dict):
                persisted["priority_view"] = {
                    level: [
                        n for n in pv.get(level, [])
                        if n.get("id") not in completed_item_ids
                    ]
                    for level in ["High", "Medium", "Low"]
                }
            persisted["todos"] = [
                t for t in persisted.get("todos", [])
                if not (set(t.get("source_note_ids", [])) <= completed_item_ids)
            ]

        fingerprint = compute_inbox_fingerprint(session)
        persisted = {
            **persisted,
            "inbox_fingerprint": fingerprint,
        }
        run.completed_at = completed_at
        run.status = ANALYSIS_SUCCEEDED
        run.mode = result["mode"]
        run.result_json = json.dumps(persisted, ensure_ascii=False)
        session.commit()
        return {
            **persisted,
            "analysis_run_id": run_id,
            "generated_at": completed_at,
            "is_stale": False,
            "inbox_fingerprint": fingerprint,
        }


def fail_analysis_run(run_id: int) -> None:
    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        run = session.get(AnalysisRunRecord, run_id)
        if run is None or run.status != ANALYSIS_RUNNING:
            return
        run.completed_at = completed_at
        run.status = ANALYSIS_FAILED
        run.mode = "error"
        run.result_json = None
        session.commit()


def get_latest_successful_analysis() -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        run = session.scalars(
            select(AnalysisRunRecord)
            .where(
                AnalysisRunRecord.status == ANALYSIS_SUCCEEDED,
                AnalysisRunRecord.owner_user_id == owner_id,
            )
            .order_by(
                AnalysisRunRecord.completed_at.desc(),
                AnalysisRunRecord.id.desc(),
            )
            .limit(1)
        ).first()
        if run is None:
            return None
        stored = json.loads(run.result_json)
        completed_item_ids = set(
            session.scalars(
                select(TaskSourceItemRecord.item_id)
                .join(TaskRecord)
                .where(
                    TaskRecord.status == TASK_COMPLETED,
                    TaskRecord.owner_user_id == owner_id,
                )
            ).all()
        )
        # The stored JSON is a snapshot; hide notes that were deleted since,
        # exactly like completed ones.
        existing_item_ids = set(
            session.scalars(
                select(InboxItemRecord.id).where(
                    InboxItemRecord.owner_user_id == owner_id
                )
            ).all()
        )
        snapshot_ids = {
            n.get("id")
            for b in stored.get("buckets", [])
            for n in b.get("notes", [])
        } | {
            i
            for t in stored.get("todos", [])
            for i in t.get("source_note_ids", [])
        }
        completed_item_ids |= snapshot_ids - existing_item_ids
        if completed_item_ids:
            filtered_buckets = []
            for b in stored.get("buckets", []):
                active_notes = [
                    n for n in b.get("notes", [])
                    if n.get("id") not in completed_item_ids
                ]
                if active_notes:
                    filtered_buckets.append({**b, "notes": active_notes})
            stored["buckets"] = filtered_buckets
            pv = stored.get("priority_view", {})
            if isinstance(pv, dict):
                stored["priority_view"] = {
                    level: [
                        n for n in pv.get(level, [])
                        if n.get("id") not in completed_item_ids
                    ]
                    for level in ["High", "Medium", "Low"]
                }
            stored["todos"] = [
                t for t in stored.get("todos", [])
                if not (set(t.get("source_note_ids", [])) <= completed_item_ids)
            ]
        fingerprint = stored.pop("inbox_fingerprint", None)
        current = compute_inbox_fingerprint(session)
        return {
            **stored,
            "analysis_run_id": run.id,
            "generated_at": run.completed_at,
            "is_stale": fingerprint != current,
            "inbox_fingerprint": fingerprint,
        }


def _task_dedup_key(source_item_ids: list[int], task_text: str = "") -> str:
    fingerprint = json.dumps(
        {
            "sources": sorted(set(source_item_ids)),
            "task": _normalize_task_text(task_text),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


DATE_FROM_NOTE = "from_note"
DATE_SUGGESTED = "suggested"
DATE_CONFIRMED = "user_confirmed"
DATE_SOURCES = (DATE_FROM_NOTE, DATE_SUGGESTED, DATE_CONFIRMED)


def _written_day(session, item_ids) -> Optional[date]:
    """The day (your time zone) you last wrote the task's note: "tomorrow" means
    the day after that, however late the note is analysed (change 012)."""
    from app.attention.dates import configured_timezone
    from app.attention.glance import local_date

    stamps = []
    for item_id in item_ids or []:
        item = session.get(InboxItemRecord, item_id)
        if item is not None and (item.updated_at or item.created_at):
            stamps.append(item.updated_at or item.created_at)
    return local_date(max(stamps), configured_timezone()) if stamps else None


def _apply_timing(
    task: TaskRecord, when: Optional[str], reference: Optional[date], ai_date: Optional[str] = None
) -> Optional[str]:
    """Read a task's timing words. A day your words name goes on due_on ("from
    your note"); a guess goes on suggested_due_on and waits for your OK.

    `ai_date` (change 014) is the filing call's suggested day. It only ever
    refines a guess: a day your words name is read by code, and a guess stays
    a suggestion that waits for your OK."""
    from app.attention.dates import date_source, normalize_time_of_day, parse_timing_phrase

    parsed = parse_timing_phrase(when, reference=reference)
    source = date_source(parsed)
    if source == DATE_SUGGESTED and _plausible_ai_date(ai_date, reference):
        parsed.normalized_iso = ai_date
    time = normalize_time_of_day(when)
    task.timing_text = when
    if source == DATE_FROM_NOTE:
        task.due_on, task.due_time = parsed.normalized_iso, time
        task.suggested_due_on = task.suggested_due_time = None
    elif source == DATE_SUGGESTED:
        task.due_on = task.due_time = None
        task.suggested_due_on, task.suggested_due_time = parsed.normalized_iso, time
    else:
        task.due_on = task.due_time = task.suggested_due_on = task.suggested_due_time = None
    task.due_confidence = source
    return source


def _plausible_ai_date(value: Optional[str], reference: Optional[date]) -> bool:
    """A real ISO day, not long before the note was written nor years away."""
    try:
        day = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    from app.attention.dates import today_in_configured_tz

    base = reference or today_in_configured_tz()
    return (base.toordinal() - 1) <= day.toordinal() <= (base.toordinal() + 3 * 366)


def _apply_filing_meta(insight: "ItemInsightRecord", meta: dict, pending: bool) -> None:
    insight.filing_rule = meta.get("rule")
    insight.filing_confidence = meta.get("confidence")
    choices = [int(choice) for choice in (meta.get("choices") or [])][:2]
    insight.filing_choices = json.dumps(choices) if choices else None
    insight.filed_by = meta.get("filed_by") if meta.get("filed_by") in FILED_BY else None
    insight.filing_pending = 1 if pending else 0
    if pending:
        insight.category = PENDING_BUCKET
        insight.topic_id = None
    insight.ai_summary = meta.get("summary") or None
    insight.suggested_action = meta.get("action") or None
    insight.memory_used = json.dumps(meta["memory_used"], ensure_ascii=False) if meta.get("memory_used") else None
    if meta.get("cleaned_transcript"):
        insight.cleaned_transcript = meta["cleaned_transcript"]


def _ensure_task_due_fields(task: TaskRecord) -> None:
    """Sort the date of a task that older code left unsorted (change 012)."""
    if task.due_confidence in DATE_SOURCES:
        return
    if task.timing_confirmed and task.due_on:
        task.due_confidence = DATE_CONFIRMED
        return
    if task.timing_text and not task.timing_confirmed:
        _apply_timing(task, task.timing_text, None)


def task_priority(task: TaskRecord) -> str:
    """The task's priority: yours when you chose one, else the AI's."""
    return task.user_priority or task.priority


def _source_context(session, item_id: Optional[int]) -> tuple[Optional[str], Optional[str]]:
    """(life area, AI's reason) of a task's first source note, from the
    note's topic (your pick, else the AI's) and its insight."""
    if item_id is None:
        return None, None
    insight = session.get(ItemInsightRecord, item_id)
    if insight is None:
        return None, None
    topic_id = insight.user_topic_id if insight.user_topic_id is not None else insight.topic_id
    topic = session.get(TopicRecord, topic_id) if topic_id is not None else None
    return (topic.bot_key if topic is not None else None), insight.rationale


def _task_to_dict(session, task: TaskRecord) -> dict:
    _ensure_task_due_fields(task)
    source_item_ids = session.scalars(
        select(TaskSourceItemRecord.item_id)
        .where(TaskSourceItemRecord.task_id == task.id)
        .order_by(TaskSourceItemRecord.item_id.asc())
    ).all()
    bot_key, reason = _source_context(session, source_item_ids[0] if source_item_ids else None)
    return {
        "id": task.id,
        "text": task.text,
        "priority": task_priority(task),
        "ai_priority": task.priority,
        "user_priority": task.user_priority,
        "bot_key": bot_key,
        "reason": reason,
        "timing_text": task.timing_text,
        "ai_timing_text": task.ai_timing_text,
        "timing_confirmed": bool(task.timing_confirmed),
        "due_on": task.due_on,
        "due_time": task.due_time,
        "due_confidence": task.due_confidence,
        "suggested_due_on": task.suggested_due_on,
        "suggested_due_time": task.suggested_due_time,
        "snoozed_until": task.snoozed_until,
        "reminder_at": task.reminder_at,
        "status": task.status,
        "source_item_ids": list(source_item_ids),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
        "someday": bool(task.someday),
        "someday_since": task.someday_since,
    }


def create_manual_task(
    text: str,
    priority: str,
    due_on: Optional[str] = None,
) -> dict:
    """Create a task directly, without requiring an inbox source item."""
    cleaned_text = text.strip()
    if not cleaned_text:
        raise ValueError("Task text cannot be empty.")

    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()

    dedup_key = hashlib.sha256(
        f"manual:{owner_id}:{uuid.uuid4().hex}".encode("utf-8")
    ).hexdigest()

    with SessionLocal() as session:
        task = TaskRecord(
            text=cleaned_text,
            priority=priority,
            timing_text=due_on,
            ai_timing_text=None,
            timing_confirmed=1 if due_on else 0,
            due_on=due_on,
            due_confidence=DATE_CONFIRMED if due_on else None,
            snoozed_until=None,
            reminder_at=None,
            status=TASK_OPEN,
            dedup_key=dedup_key,
            owner_user_id=owner_id,
            created_at=now,
            updated_at=now,
        )
        session.add(task)
        session.flush()
        session.commit()
        return _task_to_dict(session, task)


def list_tasks_from_db(
    status_filter: str = TASK_OPEN, bot: Optional[str] = None
) -> list[dict]:
    if status_filter not in TASK_STATUSES | {"all"}:
        raise ValueError("Unsupported task status")

    owner_id = require_owner_id()
    with SessionLocal() as session:
        statement = (
            select(TaskRecord)
            .where(TaskRecord.owner_user_id == owner_id)
            .order_by(TaskRecord.id.asc())
        )
        if bot is not None:
            statement = statement.where(TaskRecord.id.in_(_bot_task_ids(owner_id, bot)))
        if status_filter != "all":
            statement = statement.where(TaskRecord.status == status_filter)
        tasks = session.scalars(statement).all()
        return [_task_to_dict(session, task) for task in tasks]


def set_task_priority(task_id: int, priority: Optional[str]) -> Optional[dict]:
    """Store your priority for a task, or clear it (None) to follow the AI's."""
    if priority is not None and priority not in ("High", "Medium", "Low"):
        raise ValueError("Unsupported priority")
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        if task.user_priority != priority:
            task.user_priority = priority
            task.updated_at = datetime.now(timezone.utc).isoformat()
            if priority:
                # A correction is a memory example (change 016).
                bot_key, _ = _source_context(session, _first_source(session, task.id))
                _remember_in(session, owner_id, f"You set “{_clip_text(task.text, 80)}” to {priority} priority.",
                             kind="example", source_kind="correction", bot_key=bot_key,
                             item_ids=[i for i in [_first_source(session, task.id)] if i], status="confirmed")
            session.commit()
        return _task_to_dict(session, task)


def _first_source(session, task_id: int) -> Optional[int]:
    return session.scalar(select(TaskSourceItemRecord.item_id).where(TaskSourceItemRecord.task_id == task_id)
                          .order_by(TaskSourceItemRecord.item_id.asc()).limit(1))


def set_task_status(task_id: int, task_status: str, by: str = "you", reason: Optional[str] = None) -> Optional[dict]:
    if task_status not in TASK_STATUSES:
        raise ValueError("Unsupported task status")

    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        if task.status != task_status:
            now = datetime.now(timezone.utc).isoformat()
            kind = {TASK_COMPLETED: "done", TASK_DISMISSED: "dropped", TASK_OPEN: "reopened"}[task_status]
            session.add(TaskEventRecord(owner_user_id=owner_id, task_id=task.id, kind=kind, by=by,
                                        reason=reason if kind == "dropped" else None,
                                        from_due_on=task.due_on, created_at=now))
            task.status = task_status
            task.updated_at = now
            task.completed_at = now if task_status == TASK_COMPLETED else None
            session.commit()
        return _task_to_dict(session, task)


def list_calendar_events_from_db(
    start_date: str, end_date: str, bot: Optional[str] = None
) -> list[dict]:
    from app.attention.dates import parse_timing_phrase

    owner_id = require_owner_id()
    with SessionLocal() as session:
        # Retroactively normalize any tasks that have timing_text but missing due_on
        unnormalized = session.scalars(
            select(TaskRecord)
            .where(TaskRecord.owner_user_id == owner_id)
            .where(TaskRecord.due_on.is_(None))
            .where(TaskRecord.timing_text.isnot(None))
        ).all()
        if unnormalized:
            for task in unnormalized:
                _ensure_task_due_fields(task)
            session.commit()

        tasks = session.scalars(
            select(TaskRecord)
            .where(TaskRecord.owner_user_id == owner_id)
            .where(TaskRecord.due_on.isnot(None))
            .where(TaskRecord.due_on >= start_date)
            .where(TaskRecord.due_on <= end_date)
            .where(TaskRecord.status.in_([TASK_OPEN, TASK_COMPLETED]))
            .where(
                TaskRecord.id.in_(_bot_task_ids(owner_id, bot))
                if bot is not None
                else true()
            )
            .order_by(TaskRecord.due_on.asc(), TaskRecord.id.asc())
        ).all()

        events = []
        for task in tasks:
            sources = session.scalars(
                select(InboxItemRecord)
                .join(TaskSourceItemRecord, TaskSourceItemRecord.item_id == InboxItemRecord.id)
                .where(TaskSourceItemRecord.task_id == task.id)
                .order_by(InboxItemRecord.id.asc())
            ).all()

            source_ids = [s.id for s in sources]
            primary_source = sources[0] if sources else None
            parsed = parse_timing_phrase(task.timing_text)
            needs_confirmation = task.due_confidence == DATE_SUGGESTED
            bot_key, _reason = _source_context(session, primary_source.id if primary_source else None)

            events.append(
                {
                    "id": task.id,
                    "title": task.text,
                    "event_date": task.due_on,
                    "priority": task_priority(task),
                    "bot_key": bot_key,
                    "status": task.status,
                    "timing_text": task.timing_text,
                    "time_of_day": parsed.time_of_day,
                    "timing_confirmed": bool(task.timing_confirmed),
                    "due_confidence": task.due_confidence,
                    "needs_confirmation": bool(needs_confirmation),
                    "source_item_id": primary_source.id if primary_source else None,
                    "source_item_ids": source_ids,
                    "source_type": primary_source.item_type if primary_source else "text",
                    "source_title": primary_source.title if primary_source else None,
                }
            )
        return events


def add_pdf_item_to_db(
    original_filename: str,
    storage_path: str,
    mime_type: str,
    user_context: Optional[str] = None,
) -> dict:
    """Persist uploaded PDF metadata before text extraction."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=PDF_ITEM_TYPE,
            original_filename=original_filename,
            storage_path=storage_path,
            mime_type=mime_type,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
            user_context=user_context,
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def complete_pdf_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    extracted_text: str,
    mime_type: Optional[str],
    source_summary: Optional[str] = None,
) -> Optional[dict]:
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = extracted_text
        if source_summary:
            item.source_summary = source_summary  # change 022: AI output, made once
        item.mime_type = mime_type
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def add_image_item_to_db(
    original_filename: str,
    storage_path: str,
    mime_type: str,
    user_context: Optional[str] = None,
) -> dict:
    """Persist uploaded image metadata before OCR/description."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=IMAGE_ITEM_TYPE,
            original_filename=original_filename,
            storage_path=storage_path,
            mime_type=mime_type,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
            user_context=user_context,
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def complete_image_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    extracted_text: str,
    ai_description: str,
    mime_type: Optional[str],
) -> Optional[dict]:
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = extracted_text
        item.ai_description = ai_description
        item.mime_type = mime_type
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def add_voice_item_to_db(
    original_filename: str,
    storage_path: str,
    mime_type: str,
    user_context: Optional[str] = None,
) -> dict:
    """Persist uploaded voice note metadata before transcription."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=VOICE_ITEM_TYPE,
            original_filename=original_filename,
            storage_path=storage_path,
            mime_type=mime_type,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
            user_context=user_context,
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def complete_voice_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    extracted_text: str,
    mime_type: Optional[str],
) -> Optional[dict]:
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = extracted_text
        item.mime_type = mime_type
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def update_item_extracted_text(
    item_id: int,
    extracted_text: str,
) -> Optional[dict]:
    """User edit of extracted/OCR/transcript text (facts), preserving AI description."""
    cleaned = extracted_text.strip()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return None
        if item.item_type not in {IMAGE_ITEM_TYPE, VOICE_ITEM_TYPE, PDF_ITEM_TYPE}:
            return None
        if cleaned != (item.extracted_text or ""):
            _flag_dates_for_recheck(session, item.id)
        item.extracted_text = cleaned
        if item.item_type == IMAGE_ITEM_TYPE and item.ai_description:
            item.raw_text = (
                f"{cleaned}\n\n[AI description — inferred]\n{item.ai_description}"
                if cleaned
                else f"[AI description — inferred]\n{item.ai_description}"
            )
        else:
            item.raw_text = cleaned
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def add_url_item_to_db(url: str, user_context: Optional[str] = None) -> dict:
    """Persist URL first (captured), then return the row for processing."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=URL_ITEM_TYPE,
            source_url=url,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
            user_context=user_context,
            created_at=now,
        )
        session.add(item)
        session.commit()
        return _item_to_dict(item)


def mark_item_processing(item_id: int) -> Optional[dict]:
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return None
        item.processing_status = STATUS_PROCESSING
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def claim_item_for_retry(item_id: int) -> bool:
    """Atomically claim a non-ready item for one retry worker."""
    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        result = session.execute(
            update(InboxItemRecord)
            .where(
                InboxItemRecord.id == item_id,
                InboxItemRecord.owner_user_id == owner_id,
                InboxItemRecord.processing_status.notin_(
                    (STATUS_READY, STATUS_PROCESSING)
                ),
            )
            .values(
                processing_status=STATUS_PROCESSING,
                error_message=None,
                updated_at=now,
            )
        )
        session.commit()
        return result.rowcount == 1


def find_saved_link(url: str, exclude_item_id: Optional[int] = None) -> Optional[dict]:
    """Your newest saved link with the same tidy address that was read
    successfully (change 015: a link saved twice reuses its earlier result)."""
    from app.capture.link_card import tidy_url

    owner_id = require_owner_id()
    wanted = tidy_url(url)
    with SessionLocal() as session:
        for item in session.scalars(
            select(InboxItemRecord)
            .where(
                InboxItemRecord.owner_user_id == owner_id,
                InboxItemRecord.item_type == URL_ITEM_TYPE,
                InboxItemRecord.processing_status == STATUS_READY,
            )
            .order_by(InboxItemRecord.id.desc())
        ).all():
            if item.id != exclude_item_id and item.source_url and tidy_url(item.source_url) == wanted:
                return _item_to_dict(item)
    return None


def reuse_saved_link(item_id: int, earlier_id: int, copy_filing: bool) -> Optional[dict]:
    """A link saved again takes what was read the first time (no fetch). With
    no new note of yours, it is filed like the earlier one too (no AI call)."""
    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        earlier = session.get(InboxItemRecord, earlier_id)
        if item is None or earlier is None or item.owner_user_id != owner_id or earlier.owner_user_id != owner_id:
            return None
        for field in ("title", "raw_text", "extracted_text", "mime_type", "link_card"):
            setattr(item, field, getattr(earlier, field))
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = now
        filed = False
        old = session.get(ItemInsightRecord, earlier_id)
        if copy_filing and old is not None:
            session.add(ItemInsightRecord(
                item_id=item_id, analysis_run_id=old.analysis_run_id, category=old.category,
                concise_title=old.concise_title, priority=old.priority, topic_id=old.user_topic_id or old.topic_id,
                tags_json=old.tags_json,
                rationale=f"The same link as a note you saved before (#{earlier_id}), so it's filed the same way.",
                needs_review=0, updated_at=now, filing_rule=old.filing_rule, filing_confidence=old.filing_confidence,
                filing_choices=old.filing_choices, filed_by=old.filed_by if old.user_topic_id is None else "you",
                filing_pending=old.filing_pending if old.user_topic_id is None else 0,
                ai_summary=old.ai_summary, suggested_action=old.suggested_action,
            ))
            filed = True
        session.commit()
        result = _item_to_dict(item)
    result["reused_from"] = earlier_id
    result["filing_reused"] = filed
    return result


def complete_url_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    mime_type: Optional[str],
    final_url: Optional[str] = None,
    link_card: Optional[dict] = None,
) -> Optional[dict]:
    from app.capture.link_card import tidy_url

    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = raw_text
        item.mime_type = mime_type
        if final_url:
            item.source_url = tidy_url(final_url)
        item.link_card = json.dumps(link_card, ensure_ascii=False) if link_card else None
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def fail_item_processing(item_id: int, error_message: str) -> Optional[dict]:
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return None
        item.processing_status = STATUS_FAILED
        item.error_message = error_message[:1000]
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


def get_item_from_db(item_id: int) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.owner_user_id != owner_id:
            return None
        return _item_to_dict(item)


def confirm_task_timing(
    task_id: int,
    timing_text: Optional[str] = None,
) -> Optional[dict]:
    from app.attention.dates import normalize_time_of_day, parse_timing_phrase

    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        now = datetime.now(timezone.utc).isoformat()
        if timing_text is None or timing_text == task.timing_text:
            # Confirm the date already shown (a suggestion included). Reading
            # "tomorrow" again today would move it a day.
            new_on = task.due_on or task.suggested_due_on
            new_time = task.due_time if task.due_on else task.suggested_due_time
            if new_on is None:
                parsed = parse_timing_phrase(task.timing_text)
                new_on, new_time = parsed.normalized_iso, normalize_time_of_day(task.timing_text)
        else:
            task.timing_text = timing_text
            parsed = parse_timing_phrase(timing_text)
            new_on, new_time = parsed.normalized_iso, normalize_time_of_day(timing_text)
        if not task.timing_confirmed and new_on:
            _record_date_change(session, task, "confirmed", new_on, new_time, now)
        task.due_on = new_on
        task.due_time = new_time
        task.suggested_due_on = task.suggested_due_time = None
        task.due_confidence = DATE_CONFIRMED if new_on else None
        task.timing_confirmed = 1
        task.date_recheck = 0
        task.updated_at = now
        session.commit()
        return _task_to_dict(session, task)


def _first_source_id(session, task_id: int) -> Optional[int]:
    return session.scalar(
        select(TaskSourceItemRecord.item_id)
        .where(TaskSourceItemRecord.task_id == task_id)
        .order_by(TaskSourceItemRecord.item_id.asc())
        .limit(1)
    )


def _record_date_change(
    session, task: TaskRecord, kind: str, to_on: Optional[str], to_time: Optional[str],
    now: str, *, item_id: Optional[int] = None,
) -> None:
    session.add(TaskDateChangeRecord(
        owner_user_id=task.owner_user_id,
        task_id=task.id,
        item_id=item_id if item_id is not None else _first_source_id(session, task.id),
        task_text=task.text,
        kind=kind,
        from_due_on=task.due_on,
        from_due_time=task.due_time,
        to_due_on=to_on,
        to_due_time=to_time,
        created_at=now,
    ))


def set_task_date(task_id: int, due_on: str, due_time: Optional[str] = None, by: str = "you") -> Optional[dict]:
    """You set a task's date (Postpone / Change date, change 012). It counts as
    confirmed, works even if the date was confirmed before, and is recorded."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        now = datetime.now(timezone.utc).isoformat()
        same = task.due_on == due_on and (task.due_time or None) == (due_time or None)
        if not same:
            old = (task.due_on or "", task.due_time or "")
            new = (due_on, due_time or "")
            if not task.due_on:
                kind = "confirmed" if task.suggested_due_on == due_on else "set"
            else:
                kind = "postponed" if new > old else "moved_earlier"
            _record_date_change(session, task, kind, due_on, due_time, now)
        elif not task.timing_confirmed:
            _record_date_change(session, task, "confirmed", due_on, due_time, now)
        if not same or task.someday:
            session.add(TaskEventRecord(owner_user_id=owner_id, task_id=task.id, kind="rescheduled", by=by,
                                        from_due_on=task.due_on, to_due_on=due_on, created_at=now))
        task.someday, task.someday_since = 0, None
        task.due_on = due_on
        task.due_time = due_time
        task.suggested_due_on = task.suggested_due_time = None
        task.timing_text = f"{due_on} {due_time}" if due_time else due_on
        if not same:
            # A date you set is a short-term memory example, until a week after it (016).
            from datetime import timedelta

            source = _first_source(session, task.id)
            bot_key, _ = _source_context(session, source)
            _remember_in(session, owner_id, f"“{_clip_text(task.text, 80)}” is on {_change_day(due_on, due_time)}.",
                         kind="short_term", source_kind="correction", bot_key=bot_key,
                         item_ids=[source] if source else [], status="confirmed",
                         valid_until=(date.fromisoformat(due_on) + timedelta(days=7)).isoformat())
        task.due_confidence = DATE_CONFIRMED
        task.timing_confirmed = 1
        task.date_recheck = 0
        task.updated_at = now
        session.commit()
        return _task_to_dict(session, task)


def _change_day(iso: Optional[str], time: Optional[str]) -> str:
    try:
        day = date.fromisoformat(str(iso)[:10])
    except (TypeError, ValueError):
        return str(iso or "")
    text = f"{day.strftime('%a')} {day.day} {day.strftime('%b')}"
    return f"{text} at {time}" if time else text


def date_change_text(change: dict) -> str:
    """How an update reads on the note page and in the export."""
    frm = _change_day(change.get("from_due_on"), change.get("from_due_time"))
    to = _change_day(change.get("to_due_on"), change.get("to_due_time"))
    kind = change.get("kind")
    if kind == "postponed":
        return f"Postponed from {frm} to {to}"
    if kind == "moved_earlier":
        return f"Moved earlier, from {frm} to {to}"
    if kind == "note_edit":
        return f"Your edit moved it from {frm} to {to}" if change.get("from_due_on") else f"Your edit gave it a date: {to}"
    if kind == "confirmed":
        return f"You confirmed {to}"
    return f"Date set: {to}"


def list_item_updates(item_id: int) -> Optional[list[dict]]:
    """The date history of a note's tasks, newest first; None if not yours."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.owner_user_id != owner_id:
            return None
        rows = session.scalars(
            select(TaskDateChangeRecord)
            .where(
                TaskDateChangeRecord.owner_user_id == owner_id,
                TaskDateChangeRecord.item_id == item_id,
            )
            .order_by(TaskDateChangeRecord.id.desc())
        ).all()
        tasks = {
            task.id: task for task in session.scalars(
                select(TaskRecord).where(TaskRecord.id.in_({row.task_id for row in rows}))
            ).all()
        } if rows else {}
        updates = []
        for row in rows:
            change = {
                "id": row.id,
                "task_id": row.task_id,
                "task_text": row.task_text,
                "kind": row.kind,
                "from_due_on": row.from_due_on,
                "from_due_time": row.from_due_time,
                "to_due_on": row.to_due_on,
                "to_due_time": row.to_due_time,
                "created_at": row.created_at,
            }
            task = tasks.get(row.task_id)
            # Still waiting for your OK: the task sits on this date, unconfirmed.
            change["needs_confirmation"] = bool(
                task is not None and task.status == TASK_OPEN and not task.timing_confirmed
                and (task.due_on or task.suggested_due_on) == row.to_due_on and row.kind == "note_edit"
            )
            change["text"] = date_change_text(change)
            updates.append(change)
        return updates


def update_task_in_db(
    task_id: int,
    *,
    text: Optional[str] = None,
    priority: Optional[str] = None,
    due_on: Optional[str] = None,
    clear_due: bool = False,
) -> Optional[dict]:
    """Edit a task you own (your teammates' task editing). Each part goes
    through the same path as the rest of the app: your priority is
    user_priority (the AI's stays apart), a new date is set and recorded by
    set_task_date, and edited text is kept when analysis runs again."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        now = datetime.now(timezone.utc).isoformat()
        if text is not None:
            cleaned = text.strip()
            if not cleaned:
                raise ValueError("Task text cannot be empty.")
            task.text = cleaned
            task.user_edited = 1
        if clear_due:
            task.timing_text = None
            task.due_on = task.due_time = task.suggested_due_on = task.suggested_due_time = None
            task.due_confidence = None
            task.timing_confirmed = 0
        task.updated_at = now
        session.commit()
    if priority is not None:
        set_task_priority(task_id, priority)
    if due_on is not None and not clear_due:
        set_task_date(task_id, due_on)
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        return _task_to_dict(session, task) if task is not None else None


def snooze_task_in_db(task_id: int, until_iso_date: str) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        task.snoozed_until = until_iso_date
        task.reminder_at = until_iso_date
        task.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, task)


def set_task_reminder_in_db(task_id: int, reminder_iso_date: str) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        task.reminder_at = reminder_iso_date
        task.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, task)


def get_attention_board() -> dict:
    from app.attention.dates import (
        classify_attention_bucket,
        parse_timing_phrase,
        today_in_configured_tz,
    )
    from datetime import date as date_cls

    today = today_in_configured_tz()
    board = {
        "today": [],
        "upcoming": [],
        "overdue": [],
        "unscheduled": [],
        "snoozed": [],
        "needs_confirmation": [],
        "reference_date": today.isoformat(),
    }
    for task in list_tasks_from_db(status_filter=TASK_OPEN):
        parsed = parse_timing_phrase(task.get("timing_text"))
        due = None
        if task.get("due_on"):
            try:
                due = date_cls.fromisoformat(task["due_on"])
            except ValueError:
                due = parsed.due_date
        else:
            due = parsed.due_date
        snoozed = None
        if task.get("snoozed_until"):
            try:
                snoozed = date_cls.fromisoformat(task["snoozed_until"])
            except ValueError:
                snoozed = None
        bucket = classify_attention_bucket(due, reference=today, snoozed_until=snoozed)
        entry = {
            **task,
            "original_timing_phrase": task.get("timing_text"),
            "normalized_due_on": due.isoformat() if due else None,
            "due_confidence": task.get("due_confidence") or parsed.confidence,
            "needs_confirmation": (
                (not task.get("timing_confirmed"))
                and parsed.needs_confirmation
            ),
            "attention_bucket": bucket,
            "parse_note": parsed.note,
        }
        board[bucket].append(entry)
        if entry["needs_confirmation"]:
            board["needs_confirmation"].append(entry)
    return board


def get_daily_briefing() -> dict:
    board = get_attention_board()
    priority_rank = {"High": 0, "Medium": 1, "Low": 2}
    focus = sorted(
        board["overdue"] + board["today"],
        key=lambda item: (
            priority_rank.get(item.get("priority"), 9),
            item.get("normalized_due_on") or "9999",
        ),
    )
    suggestions = []
    for item in focus[:5]:
        reason = []
        if item["attention_bucket"] == "overdue":
            reason.append("overdue")
        if item["attention_bucket"] == "today":
            reason.append("due today")
        if item.get("priority") == "High":
            reason.append("high priority")
        suggestions.append(
            {
                "task_id": item["id"],
                "text": item["text"],
                "priority": item["priority"],
                "reason": ", ".join(reason) or "on your attention list",
            }
        )
    return {
        "reference_date": board["reference_date"],
        "counts": {
            "overdue": len(board["overdue"]),
            "today": len(board["today"]),
            "upcoming": len(board["upcoming"]),
            "unscheduled": len(board["unscheduled"]),
            "snoozed": len(board["snoozed"]),
            "needs_confirmation": len(board["needs_confirmation"]),
        },
        "focus": focus[:10],
        "priority_suggestions": suggestions,
        "summary": (
            f"{len(board['overdue'])} overdue, {len(board['today'])} due today, "
            f"{len(board['upcoming'])} upcoming."
        ),
    }


def get_notification_settings() -> dict:
    from app.attention.dates import configured_timezone

    user_id = require_owner_id()
    with SessionLocal() as session:
        preferences = session.get(NotificationPreferenceRecord, user_id)
        subscription_count = session.scalar(
            select(func.count(PushSubscriptionRecord.id)).where(
                PushSubscriptionRecord.user_id == user_id
            )
        )
        return {
            "configured": preferences is not None,
            "enabled": bool(preferences.enabled) if preferences else False,
            "daily_digest_time": (
                preferences.daily_digest_time if preferences else "08:00"
            ),
            "timezone": (
                preferences.timezone
                if preferences
                else configured_timezone().key
            ),
            "include_unscheduled_prompt": (
                bool(preferences.include_unscheduled_prompt)
                if preferences
                else False
            ),
            "subscription_count": int(subscription_count or 0),
        }


def save_notification_settings(
    *,
    enabled: bool,
    daily_digest_time: str,
    timezone_name: str,
    include_unscheduled_prompt: bool,
) -> dict:
    user_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        preferences = session.get(NotificationPreferenceRecord, user_id)
        subscription_count = session.scalar(
            select(func.count(PushSubscriptionRecord.id)).where(
                PushSubscriptionRecord.user_id == user_id
            )
        )
        if enabled and not subscription_count:
            raise ValueError(
                "Enable browser notifications on this device before saving."
            )
        if preferences is None:
            preferences = NotificationPreferenceRecord(
                user_id=user_id,
                updated_at=now,
            )
            session.add(preferences)
        preferences.enabled = int(enabled)
        preferences.daily_digest_time = daily_digest_time
        preferences.timezone = timezone_name
        preferences.include_unscheduled_prompt = int(
            include_unscheduled_prompt
        )
        preferences.updated_at = now
        session.commit()
    return get_notification_settings()


def save_push_subscription(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
) -> None:
    user_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        subscription = session.scalar(
            select(PushSubscriptionRecord).where(
                PushSubscriptionRecord.endpoint == endpoint
            )
        )
        if subscription is not None and subscription.user_id != user_id:
            raise ValueError(
                "This browser subscription is associated with another account."
            )
        if subscription is None:
            subscription = PushSubscriptionRecord(
                user_id=user_id,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                created_at=now,
                updated_at=now,
            )
            session.add(subscription)
        else:
            subscription.p256dh = p256dh
            subscription.auth = auth
            subscription.updated_at = now
        session.commit()


def remove_push_subscription(endpoint: str) -> bool:
    user_id = require_owner_id()
    with SessionLocal() as session:
        subscription = session.scalar(
            select(PushSubscriptionRecord).where(
                PushSubscriptionRecord.endpoint == endpoint,
                PushSubscriptionRecord.user_id == user_id,
            )
        )
        if subscription is None:
            return False
        session.delete(subscription)
        session.commit()
        return True


def list_notification_users() -> list[dict]:
    with SessionLocal() as session:
        rows = session.execute(
            select(NotificationPreferenceRecord).where(
                NotificationPreferenceRecord.enabled == 1
            )
        ).scalars().all()
        users = []
        for row in rows:
            # Scout's weekly catch-up push (change 018) reads these; read only.
            settings = session.get(UserSettingsRecord, row.user_id)
            users.append({
                "user_id": row.user_id,
                "daily_digest_time": row.daily_digest_time,
                "timezone": row.timezone,
                "include_unscheduled_prompt": bool(
                    row.include_unscheduled_prompt
                ),
                "catchup_day": settings.catchup_day if settings else "sun",
                "catchup_time": settings.catchup_time if settings else "19:00",
                "last_catchup_at": settings.last_catchup_at if settings else None,
                "created_at": settings.created_at if settings else None,
                "away_days": settings.away_days if settings else None,
            })
        return users


def list_notification_tasks(user_id: int) -> list[dict]:
    with SessionLocal() as session:
        tasks = session.scalars(
            select(TaskRecord)
            .where(
                TaskRecord.owner_user_id == user_id,
                TaskRecord.status == TASK_OPEN,
            )
            .order_by(TaskRecord.due_on.asc(), TaskRecord.id.asc())
        ).all()
        result = []
        for task in tasks:
            _ensure_task_due_fields(task)
            source_count = session.scalar(
                select(func.count(TaskSourceItemRecord.item_id)).where(
                    TaskSourceItemRecord.task_id == task.id
                )
            )
            result.append(
                {
                    "id": task.id,
                    "text": task.text,
                    "priority": task_priority(task),
                    "due_on": task.due_on,
                    "due_time": task.due_time,
                    "timing_text": task.timing_text,
                    "timing_confirmed": bool(task.timing_confirmed),
                    "due_confidence": task.due_confidence,
                    "snoozed_until": task.snoozed_until,
                    "someday": bool(task.someday),
                    "ai_generated": bool(source_count),
                }
            )
        return result


def list_push_subscriptions(user_id: int) -> list[dict]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(PushSubscriptionRecord).where(
                PushSubscriptionRecord.user_id == user_id
            )
        ).all()
        return [
            {
                "id": row.id,
                "endpoint": row.endpoint,
                "p256dh": row.p256dh,
                "auth": row.auth,
            }
            for row in rows
        ]


def delete_push_subscription_by_id(subscription_id: int) -> None:
    with SessionLocal() as session:
        row = session.get(PushSubscriptionRecord, subscription_id)
        if row is not None:
            session.delete(row)
            session.commit()


def claim_notification_delivery(
    *,
    user_id: int,
    task_id: Optional[int],
    kind: str,
    local_date: str,
    idempotency_key: str,
    now: datetime,
) -> bool:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    now_iso = now.astimezone(timezone.utc).isoformat()
    insert_factory = (
        pg_insert if engine.dialect.name == "postgresql" else sqlite_insert
    )
    with SessionLocal() as session:
        statement = insert_factory(NotificationDeliveryRecord).values(
            user_id=user_id,
            task_id=task_id,
            kind=kind,
            local_date=local_date,
            idempotency_key=idempotency_key,
            status="sending",
            attempts=1,
            created_at=now_iso,
            updated_at=now_iso,
        )
        result = session.execute(
            statement.on_conflict_do_nothing(
                index_elements=["idempotency_key"]
            )
        )
        if result.rowcount == 1:
            session.commit()
            return True

        record = session.scalar(
            select(NotificationDeliveryRecord)
            .where(
                NotificationDeliveryRecord.idempotency_key == idempotency_key
            )
            .with_for_update()
        )
        if record is None or record.status == "sent" or record.attempts >= 5:
            session.rollback()
            return False

        retry_after = now - timedelta(minutes=5)
        try:
            updated_at = datetime.fromisoformat(record.updated_at)
        except ValueError:
            updated_at = now
        if record.status == "sending" and updated_at > retry_after:
            session.rollback()
            return False
        if record.status == "failed" and updated_at > retry_after:
            session.rollback()
            return False

        record.status = "sending"
        record.attempts += 1
        record.updated_at = now_iso
        record.last_error = None
        session.commit()
        return True


def finish_notification_delivery(
    idempotency_key: str,
    *,
    delivered: bool,
    now: datetime,
    error: Optional[str] = None,
) -> None:
    now_iso = now.astimezone(timezone.utc).isoformat()
    with SessionLocal() as session:
        record = session.scalar(
            select(NotificationDeliveryRecord).where(
                NotificationDeliveryRecord.idempotency_key == idempotency_key
            )
        )
        if record is None:
            raise ValueError("Notification delivery claim was lost.")
        record.status = "sent" if delivered else "failed"
        record.updated_at = now_iso
        record.delivered_at = now_iso if delivered else None
        record.last_error = None if delivered else (error or "Delivery failed.")[:1000]
        session.commit()


def save_calendar_receipt(
    *,
    draft_id: str,
    task_id: int,
    provider: str,
    status: str,
    payload: dict,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        receipt = CalendarActionReceiptRecord(
            draft_id=draft_id,
            task_id=task_id,
            provider=provider,
            status=status,
            payload_json=json.dumps(payload),
            created_at=now,
        )
        session.add(receipt)
        session.commit()
        return {
            "id": receipt.id,
            "draft_id": receipt.draft_id,
            "task_id": receipt.task_id,
            "provider": receipt.provider,
            "status": receipt.status,
            "payload": payload,
            "created_at": receipt.created_at,
        }


def _topic_to_dict(
    topic: TopicRecord, item_count: int = 0, total_item_count: Optional[int] = None
) -> dict:
    return {
        "id": topic.id,
        "name": topic.name,
        "description": topic.description,
        "archived": bool(topic.archived),
        "item_count": item_count,
        "total_item_count": item_count if total_item_count is None else total_item_count,
        "parent_topic_id": topic.parent_topic_id,
        "bot_key": topic.bot_key,
        "origin": topic.origin or ORIGIN_USER,
        "is_built_in": topic.origin == ORIGIN_BUILT_IN,
        "created_at": topic.created_at,
        "updated_at": topic.updated_at,
        "proposed_by": topic.proposed_by,
        "evidence_item_ids": json.loads(topic.evidence_item_ids) if topic.evidence_item_ids else [],
        "approved_at": topic.approved_at,
    }


def list_topics_from_db(
    include_archived: bool = False, bot: Optional[str] = None
) -> list[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        session.commit()
        statement = (
            select(TopicRecord)
            .where(TopicRecord.owner_user_id == owner_id)
            .order_by(TopicRecord.name.asc())
        )
        if not include_archived:
            statement = statement.where(TopicRecord.archived == 0)
        if bot is not None:
            statement = statement.where(TopicRecord.bot_key == bot)
        topics = session.scalars(statement).all()
        counts = {}
        # Completed notes leave the active views, so they don't count here
        # (your teammates' rule, with its test in test_isolation_regressions).
        done_item_ids = set(
            session.scalars(
                select(TaskSourceItemRecord.item_id)
                .join(TaskRecord)
                .where(
                    TaskRecord.status == TASK_COMPLETED,
                    TaskRecord.owner_user_id == owner_id,
                )
            ).all()
        )
        for insight in session.scalars(
            select(ItemInsightRecord)
            .join(InboxItemRecord, ItemInsightRecord.item_id == InboxItemRecord.id)
            .where(InboxItemRecord.owner_user_id == owner_id)
        ).all():
            if insight.item_id in done_item_ids:
                continue
            effective_topic = (
                insight.user_topic_id
                if insight.user_topic_id is not None
                else insight.topic_id
            )
            if effective_topic is None:
                continue
            counts[effective_topic] = counts.get(effective_topic, 0) + 1
        # A parent's total includes the notes filed in its subtopics.
        totals = dict(counts)
        for topic in topics:
            if topic.parent_topic_id is not None:
                totals[topic.parent_topic_id] = totals.get(
                    topic.parent_topic_id, 0
                ) + counts.get(topic.id, 0)
        return [
            _topic_to_dict(topic, counts.get(topic.id, 0), totals.get(topic.id, 0))
            for topic in topics
        ]


def _validate_parent_topic(session, owner_id: int, parent_topic_id: int) -> TopicRecord:
    parent = session.get(TopicRecord, parent_topic_id)
    if parent is None or parent.owner_user_id != owner_id or parent.archived:
        raise TopicConflictError("Parent topic not found.")
    if parent.parent_topic_id is not None:
        raise TopicConflictError(
            "Subtopics can only sit under a main topic, not under another subtopic."
        )
    if parent.name == CATCH_ALL_TOPIC:
        raise TopicConflictError(
            f"\u201c{CATCH_ALL_TOPIC}\u201d is the catch-all topic and cannot have subtopics."
        )
    return parent


def topic_name_exists(name: str) -> bool:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        session.commit()
        return (
            session.scalars(
                select(TopicRecord.id).where(
                    func.lower(TopicRecord.name) == name.strip().lower(),
                    TopicRecord.owner_user_id == owner_id,
                    TopicRecord.archived == 0,
                )
            ).first()
            is not None
        )


def create_topic_in_db(
    name: str,
    description: Optional[str] = None,
    parent_topic_id: Optional[int] = None,
    bot_key: Optional[str] = None,
) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        if parent_topic_id is not None:
            parent = _validate_parent_topic(session, owner_id, parent_topic_id)
            if bot_key is not None and bot_key != parent.bot_key:
                raise TopicConflictError(
                    "A subtopic always belongs to its parent's life area."
                )
            chosen_bot = parent.bot_key
        else:
            if bot_key is not None and bot_key not in bots.BOTS_BY_KEY:
                raise TopicConflictError("Unknown life area.")
            chosen_bot = bot_key or bots.bot_for_text(f"{name} {description or ''}")
        existing = session.scalars(
            select(TopicRecord).where(
                func.lower(TopicRecord.name) == name.strip().lower(),
                TopicRecord.owner_user_id == owner_id,
            )
        ).first()
        if existing is not None:
            if existing.archived:
                existing.archived = 0
                existing.description = description
                existing.parent_topic_id = parent_topic_id
                if existing.origin != ORIGIN_BUILT_IN:
                    existing.bot_key = chosen_bot
                existing.updated_at = now
                session.commit()
                return _topic_to_dict(existing)
            raise ValueError("Topic already exists")
        topic = TopicRecord(
            name=name,
            description=description,
            owner_user_id=owner_id,
            created_at=now,
            updated_at=now,
            archived=0,
            parent_topic_id=parent_topic_id,
            bot_key=chosen_bot,
            origin=ORIGIN_USER,
        )
        session.add(topic)
        session.commit()
        return _topic_to_dict(topic)


def _deletable_topic(session, owner_id: int, topic_id: int) -> Optional[TopicRecord]:
    topic = session.get(TopicRecord, topic_id)
    if topic is None or topic.owner_user_id != owner_id:
        return None
    if topic.origin == ORIGIN_BUILT_IN:
        raise TopicConflictError("Built-in topics can't be deleted.")
    return topic


def _topic_insights(session, owner_id: int, topic_id: int) -> list:
    """Owner's insights that point at the topic, as AI topic or user choice."""
    return session.scalars(
        select(ItemInsightRecord)
        .join(InboxItemRecord, ItemInsightRecord.item_id == InboxItemRecord.id)
        .where(
            InboxItemRecord.owner_user_id == owner_id,
            or_(
                ItemInsightRecord.topic_id == topic_id,
                ItemInsightRecord.user_topic_id == topic_id,
            ),
        )
    ).all()


def _live_parent(session, owner_id: int, topic: TopicRecord) -> Optional[TopicRecord]:
    if topic.parent_topic_id is None:
        return None
    parent = session.get(TopicRecord, topic.parent_topic_id)
    if parent is None or parent.owner_user_id != owner_id or parent.archived:
        return None
    return parent


def get_topic_deletion_plan(topic_id: int) -> Optional[dict]:
    """What deleting a topic would affect. None if it isn't the user's topic.

    Raises TopicConflictError for built-in topics.
    """
    owner_id = require_owner_id()
    with SessionLocal() as session:
        topic = _deletable_topic(session, owner_id, topic_id)
        if topic is None:
            return None
        parent = _live_parent(session, owner_id, topic)
        subtopics = session.scalars(
            select(TopicRecord).where(
                TopicRecord.parent_topic_id == topic.id,
                TopicRecord.owner_user_id == owner_id,
            )
        ).all()
        notes = []
        for insight in _topic_insights(session, owner_id, topic.id):
            item = session.get(InboxItemRecord, insight.item_id)
            text = (
                "\n\n".join(
                    part
                    for part in (
                        item.user_context,
                        item.extracted_text or item.raw_text or item.title,
                    )
                    if part
                )
                if item
                else ""
            )
            notes.append({"id": insight.item_id, "text": text})
        return {
            "topic": {"id": topic.id, "name": topic.name},
            "parent": {"id": parent.id, "name": parent.name} if parent else None,
            "subtopics": [{"id": t.id, "name": t.name} for t in subtopics],
            "notes": notes,
        }


def _rewrite_latest_analysis_buckets(
    session, owner_id: int, deleted_name: str, new_bucket_for_item: dict[int, str]
) -> None:
    """Keep the stored "AI-organized inbox" view from showing a deleted topic."""
    run = session.scalars(
        select(AnalysisRunRecord)
        .where(
            AnalysisRunRecord.status == ANALYSIS_SUCCEEDED,
            AnalysisRunRecord.owner_user_id == owner_id,
        )
        .order_by(AnalysisRunRecord.completed_at.desc(), AnalysisRunRecord.id.desc())
        .limit(1)
    ).first()
    if run is None or not run.result_json:
        return
    stored = json.loads(run.result_json)
    buckets = stored.get("buckets") or []
    deleted_key = deleted_name.strip().lower()
    moved_notes = []
    kept = []
    for bucket in buckets:
        if str(bucket.get("name", "")).strip().lower() == deleted_key:
            moved_notes.extend(bucket.get("notes") or [])
        else:
            kept.append(bucket)
    if not moved_notes:
        return
    by_name = {str(b.get("name", "")).strip().lower(): b for b in kept}
    for note in moved_notes:
        target = new_bucket_for_item.get(note.get("id"), CATCH_ALL_TOPIC)
        bucket = by_name.get(target.lower())
        if bucket is None:
            bucket = {"name": target, "notes": []}
            kept.append(bucket)
            by_name[target.lower()] = bucket
        bucket.setdefault("notes", []).append(note)
    stored["buckets"] = kept
    run.result_json = json.dumps(stored, ensure_ascii=False)


def delete_topic_in_db(
    topic_id: int, assignments: dict[int, Optional[str]], choices_for: Optional[dict[int, list[int]]] = None
) -> Optional[dict]:
    """Delete a user topic and re-home its notes, in one transaction.

    - Subtopic: its notes move to the parent topic.
    - Main topic: each note goes to ``assignments[item_id]`` (an existing
      topic name chosen by the caller). When none fits, it waits in Needs you
      with ``choices_for[item_id]`` (change 014: no catch-all).
    - Its own subtopics become main topics.
    """
    choices_for = choices_for or {}
    owner_id = require_owner_id()
    with SessionLocal() as session:
        topic = _deletable_topic(session, owner_id, topic_id)
        if topic is None:
            return None
        parent = _live_parent(session, owner_id, topic)
        others = {
            t.name.strip().lower(): t
            for t in session.scalars(
                select(TopicRecord).where(
                    TopicRecord.owner_user_id == owner_id,
                    TopicRecord.id != topic.id,
                    TopicRecord.archived == 0,
                )
            ).all()
        }
        others.pop(CATCH_ALL_TOPIC.lower(), None)  # never a destination (change 014)
        now = datetime.now(timezone.utc).isoformat()

        moved = []
        new_bucket_for_item = {}
        for insight in _topic_insights(session, owner_id, topic.id):
            was_in_topic = (
                insight.user_topic_id == topic.id
                or (insight.user_topic_id is None and insight.topic_id == topic.id)
            )
            if parent is not None:
                destination = parent
                if insight.topic_id == topic.id:
                    insight.topic_id = parent.id
                    insight.category = parent.name
                if insight.user_topic_id == topic.id:
                    # The user chose this topic; keep the choice, one level up.
                    insight.user_topic_id = parent.id
            else:
                chosen = assignments.get(insight.item_id)
                destination = others.get(chosen.strip().lower()) if chosen else None
                if destination is None:
                    # Nothing fits: no guess, it waits in Needs you (rule R6).
                    choices = [c for c in choices_for.get(insight.item_id, []) if c != topic.id][:2]
                    insight.topic_id = None
                    insight.category = PENDING_BUCKET
                    insight.filing_pending = 1
                    insight.filing_rule = "R6"
                    insight.filing_confidence = "low"
                    insight.filing_choices = json.dumps(choices) if choices else None
                    if insight.user_topic_id == topic.id:
                        insight.user_topic_id = None
                    insight.updated_at = now
                    new_bucket_for_item[insight.item_id] = PENDING_BUCKET
                    if was_in_topic:
                        moved.append({"item_id": insight.item_id, "topic_id": None, "topic_name": PENDING_BUCKET})
                    continue
                insight.topic_id = destination.id
                insight.category = destination.name
                if insight.user_topic_id == topic.id:
                    insight.user_topic_id = None
            insight.updated_at = now
            new_bucket_for_item[insight.item_id] = destination.name
            if was_in_topic:
                moved.append(
                    {
                        "item_id": insight.item_id,
                        "topic_id": destination.id,
                        "topic_name": destination.name,
                    }
                )

        promoted = []
        for child in session.scalars(
            select(TopicRecord).where(TopicRecord.parent_topic_id == topic.id)
        ).all():
            child.parent_topic_id = None
            child.updated_at = now
            promoted.append({"id": child.id, "name": child.name})

        _rewrite_latest_analysis_buckets(session, owner_id, topic.name, new_bucket_for_item)
        deleted = {"id": topic.id, "name": topic.name}
        session.flush()
        session.delete(topic)
        session.commit()
        return {
            "deleted": deleted,
            "moved_to_parent": {"id": parent.id, "name": parent.name} if parent else None,
            "moved_notes": moved,
            "promoted_subtopics": promoted,
        }


def _topic_by_id(session, topic_id: int) -> TopicRecord:
    return session.get(TopicRecord, topic_id)


def update_topic_in_db(
    topic_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    archived: Optional[bool] = None,
    bot_key: Optional[str] = None,
) -> Optional[dict]:
    """Edit a topic. A new `bot_key` moves a main topic, with its subtopics,
    to another life area; built-in topics stay in their own area."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        topic = session.get(TopicRecord, topic_id)
        if topic is not None and topic.owner_user_id != owner_id:
            return None
        if topic is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        if bot_key is not None and bot_key != topic.bot_key:
            if bot_key not in bots.BOTS_BY_KEY:
                raise TopicConflictError("Unknown life area.")
            if topic.origin == ORIGIN_BUILT_IN:
                raise TopicConflictError("Built-in topics stay in their own life area.")
            if topic.parent_topic_id is not None:
                raise TopicConflictError("A subtopic moves with its parent topic.")
            topic.bot_key = bot_key
            for child in session.scalars(
                select(TopicRecord).where(
                    TopicRecord.parent_topic_id == topic.id,
                    TopicRecord.owner_user_id == owner_id,
                )
            ).all():
                child.bot_key = bot_key
                child.updated_at = now
        if name is not None and name.strip() != topic.name:
            new_name = name.strip()
            clash = session.scalars(
                select(TopicRecord).where(
                    TopicRecord.owner_user_id == owner_id,
                    TopicRecord.id != topic.id,
                    func.lower(TopicRecord.name) == new_name.lower(),
                )
            ).first()
            if clash is not None:
                raise TopicConflictError(f"You already have a topic called “{clash.name}”.")
            _rename_topic_references(session, owner_id, topic.name, new_name)
            topic.name = new_name
        if description is not None:
            topic.description = description
        if archived is not None:
            topic.archived = 1 if archived else 0
        topic.updated_at = now
        session.commit()
        return _topic_to_dict(topic)


def _rename_topic_references(session, owner_id: int, old: str, new: str) -> None:
    """A topic's name is also stored as its notes' category and as a bucket
    name in saved analyses (v1). Rename those too, so filters and the
    AI-organized view keep matching the topic."""
    owned_items = select(InboxItemRecord.id).where(InboxItemRecord.owner_user_id == owner_id)
    for insight in session.scalars(
        select(ItemInsightRecord).where(
            ItemInsightRecord.item_id.in_(owned_items),
            func.lower(ItemInsightRecord.category) == old.strip().lower(),
        )
    ).all():
        insight.category = new
    for run in session.scalars(
        select(AnalysisRunRecord).where(
            AnalysisRunRecord.owner_user_id == owner_id,
            AnalysisRunRecord.result_json.is_not(None),
        )
    ).all():
        try:
            stored = json.loads(run.result_json)
        except (TypeError, ValueError):
            continue
        buckets = stored.get("buckets") if isinstance(stored, dict) else None
        if not isinstance(buckets, list):
            continue
        changed = False
        for bucket in buckets:
            if isinstance(bucket, dict) and str(bucket.get("name", "")).strip().lower() == old.strip().lower():
                bucket["name"] = new
                changed = True
        if changed:
            run.result_json = json.dumps(stored, ensure_ascii=False)


# --- the lens: what belongs to one life area ------------------------------------


def _bot_item_ids(owner_id: int, bot_key: str):
    """Ids of the owner's items whose topic (the user's pick, else the AI's)
    belongs to the life area. A subquery, for `.in_()`."""
    topic_ids = select(TopicRecord.id).where(
        TopicRecord.owner_user_id == owner_id, TopicRecord.bot_key == bot_key
    )
    return (
        select(ItemInsightRecord.item_id)
        .join(InboxItemRecord, ItemInsightRecord.item_id == InboxItemRecord.id)
        .where(
            InboxItemRecord.owner_user_id == owner_id,
            func.coalesce(
                ItemInsightRecord.user_topic_id, ItemInsightRecord.topic_id
            ).in_(topic_ids),
        )
    )


def _topic_item_ids(owner_id: int, topic_id: int):
    """Ids of the owner's items filed in the topic or one of its subtopics
    (the user's pick, else the AI's). A subquery, for `.in_()`."""
    topic_ids = select(TopicRecord.id).where(
        TopicRecord.owner_user_id == owner_id,
        or_(TopicRecord.id == topic_id, TopicRecord.parent_topic_id == topic_id),
    )
    return (
        select(ItemInsightRecord.item_id)
        .join(InboxItemRecord, ItemInsightRecord.item_id == InboxItemRecord.id)
        .where(
            InboxItemRecord.owner_user_id == owner_id,
            func.coalesce(
                ItemInsightRecord.user_topic_id, ItemInsightRecord.topic_id
            ).in_(topic_ids),
        )
    )


def owns_topic(topic_id: int) -> bool:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        topic = session.get(TopicRecord, topic_id)
        return topic is not None and topic.owner_user_id == owner_id


def get_topic_detail(topic_id: int) -> Optional[dict]:
    """One topic with its counts, plus how many of its notes (subtopics
    included) are of each kind, for the topic page's filters."""
    owner_id = require_owner_id()
    topic = next(
        (row for row in list_topics_from_db(include_archived=True) if row["id"] == topic_id),
        None,
    )
    if topic is None:
        return None
    with SessionLocal() as session:
        rows = session.execute(
            select(InboxItemRecord.item_type, func.count())
            .where(InboxItemRecord.id.in_(_topic_item_ids(owner_id, topic_id)))
            .group_by(InboxItemRecord.item_type)
        ).all()
    topic["type_counts"] = {item_type: count for item_type, count in rows}
    return topic


def _bot_task_ids(owner_id: int, bot_key: str):
    """Ids of tasks with at least one source item in the life area."""
    return select(TaskSourceItemRecord.task_id).where(
        TaskSourceItemRecord.item_id.in_(_bot_item_ids(owner_id, bot_key))
    )


def glance_rows() -> dict:
    """The owner's notes (with their topic and area), tasks and topics, for
    the Dashboard (app/attention/glance.py)."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        rows = session.execute(
            select(
                InboxItemRecord.id,
                InboxItemRecord.created_at,
                ItemInsightRecord.user_topic_id,
                ItemInsightRecord.topic_id,
            )
            .outerjoin(ItemInsightRecord, ItemInsightRecord.item_id == InboxItemRecord.id)
            .where(InboxItemRecord.owner_user_id == owner_id)
        ).all()
        topic_bots = dict(
            session.execute(
                select(TopicRecord.id, TopicRecord.bot_key).where(TopicRecord.owner_user_id == owner_id)
            ).all()
        )
    items = []
    for item_id, created_at, user_topic_id, ai_topic_id in rows:
        topic_id = user_topic_id if user_topic_id is not None else ai_topic_id
        items.append({
            "id": item_id,
            "created_at": created_at,
            "topic_id": topic_id,
            "bot_key": topic_bots.get(topic_id),
        })
    return {
        "items": items,
        "tasks": list_tasks_from_db(status_filter="all"),
        "topics": list_topics_from_db(),
    }


def bots_for_items(item_ids: list[int]) -> dict[int, str]:
    """The life area each of your notes is filed in (Ask me's routing, 019)."""
    owner_id = require_owner_id()
    found: dict[int, str] = {}
    with SessionLocal() as session:
        for item_id in set(item_ids):
            item = session.get(InboxItemRecord, item_id)
            if item is None or item.owner_user_id != owner_id:
                continue
            bot_key, _ = _source_context(session, item_id)
            if bot_key:
                found[item_id] = bot_key
    return found


def item_ids_for_bot(bot_key: str) -> set[int]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        return set(session.scalars(_bot_item_ids(owner_id, bot_key)).all())


def _short_date(iso_date: str) -> str:
    try:
        day = date.fromisoformat(iso_date[:10])
    except ValueError:
        return iso_date
    return f"{day:%a} {day.day} {day:%b}"


def _bot_status_line(next_task, open_tasks: int, items: int) -> str:
    if next_task is not None:
        text = next_task.text if len(next_task.text) <= 40 else next_task.text[:39].rstrip() + "\u2026"
        when = _short_date(next_task.due_on or next_task.suggested_due_on)
        time = next_task.due_time or next_task.suggested_due_time
        if time:
            when = f"{when} {time}"
        if not next_task.due_on:
            when += "?"  # a suggestion, waiting for your OK
        return f"{text} \u00b7 {when}"
    if open_tasks:
        return f"{open_tasks} open task{'' if open_tasks == 1 else 's'}, no dates"
    if items:
        return f"{items} note{'' if items == 1 else 's'}"
    return "Nothing yet"


def list_bots_from_db() -> list[dict]:
    """The five life areas, with counts and a one-line status for each."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        session.commit()
        result = []
        for bot in bots.BOTS:
            topic_count = session.scalar(
                select(func.count())
                .select_from(TopicRecord)
                .where(
                    TopicRecord.owner_user_id == owner_id,
                    TopicRecord.bot_key == bot.key,
                    TopicRecord.archived == 0,
                )
            ) or 0
            item_count = session.scalar(
                select(func.count()).select_from(
                    _bot_item_ids(owner_id, bot.key).subquery()
                )
            ) or 0
            open_tasks = session.scalars(
                select(TaskRecord).where(
                    TaskRecord.owner_user_id == owner_id,
                    TaskRecord.status == TASK_OPEN,
                    TaskRecord.id.in_(_bot_task_ids(owner_id, bot.key)),
                )
            ).all()
            for task in open_tasks:
                _ensure_task_due_fields(task)
            dated = sorted(
                (task for task in open_tasks if task.due_on or task.suggested_due_on),
                key=lambda task: (task.due_on or task.suggested_due_on, task.due_time or "", task.id),
            )
            next_task = dated[0] if dated else None
            result.append(
                {
                    "key": bot.key,
                    "name": bot.name,
                    "description": bot.description,
                    "topic_count": topic_count,
                    "item_count": item_count,
                    "open_task_count": len(open_tasks),
                    "next_task": (
                        {
                            "id": next_task.id,
                            "text": next_task.text,
                            "due_on": next_task.due_on or next_task.suggested_due_on,
                            "due_time": next_task.due_time or next_task.suggested_due_time,
                            "suggested": not next_task.due_on,
                        }
                        if next_task
                        else None
                    ),
                    "status": _bot_status_line(next_task, len(open_tasks), item_count),
                }
            )
        return result


def _parse_tags(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(tag) for tag in value]


def _parse_memory_used(raw: Optional[str]) -> list[dict]:
    try:
        value = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [entry for entry in value if isinstance(entry, dict) and entry.get("text")] if isinstance(value, list) else []


def _insight_to_dict(insight: ItemInsightRecord) -> dict:
    from app.sensitive import mask_secrets

    # A title never shows a secret (change 016).
    effective_title = mask_secrets(insight.user_title or insight.concise_title) or None
    effective_priority = insight.user_priority or insight.priority
    effective_topic_id = (
        insight.user_topic_id
        if insight.user_topic_id is not None
        else insight.topic_id
    )
    effective_tags = (
        _parse_tags(insight.user_tags_json)
        if insight.user_tags_json is not None
        else _parse_tags(insight.tags_json)
    )
    return {
        "item_id": insight.item_id,
        "analysis_run_id": insight.analysis_run_id,
        "category": insight.category,
        "concise_title": insight.concise_title,
        "priority": insight.priority,
        "topic_id": insight.topic_id,
        "tags": _parse_tags(insight.tags_json),
        "rationale": insight.rationale,
        "user_title": insight.user_title,
        "user_topic_id": insight.user_topic_id,
        "user_priority": insight.user_priority,
        "user_tags": (
            _parse_tags(insight.user_tags_json)
            if insight.user_tags_json is not None
            else None
        ),
        "effective_title": effective_title,
        "effective_priority": effective_priority,
        "effective_topic_id": effective_topic_id,
        "effective_tags": effective_tags,
        "memory_used": _parse_memory_used(insight.memory_used),
        "filing_rule": insight.filing_rule,
        "filing_confidence": insight.filing_confidence,
        "filing_choices": json.loads(insight.filing_choices) if insight.filing_choices else [],
        "filed_by": "you" if insight.user_topic_id is not None else insight.filed_by,
        "filing_pending": bool(insight.filing_pending) and insight.user_topic_id is None,
        "ai_summary": insight.ai_summary,
        "suggested_action": insight.suggested_action,
        "cleaned_transcript": insight.cleaned_transcript,
        "needs_review": bool(insight.needs_review),
        "updated_at": insight.updated_at,
        "has_user_overrides": any(
            [
                insight.user_title is not None,
                insight.user_topic_id is not None,
                insight.user_priority is not None,
                insight.user_tags_json is not None,
            ]
        ),
    }


def get_item_insight(item_id: int) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.owner_user_id != owner_id:
            return None
        insight = session.get(ItemInsightRecord, item_id)
        if insight is None:
            return None
        return _insight_to_dict(insight)


def update_item_insight_overrides(
    item_id: int,
    user_title: Optional[str] = None,
    user_topic_id: Optional[int] = None,
    user_priority: Optional[str] = None,
    user_tags: Optional[list[str]] = None,
    clear_overrides: bool = False,
    needs_review: Optional[bool] = None,
) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.owner_user_id != owner_id:
            return None
        insight = session.get(ItemInsightRecord, item_id)
        if insight is None:
            return None
        if clear_overrides:
            insight.user_title = None
            insight.user_topic_id = None
            insight.user_priority = None
            insight.user_tags_json = None
        else:
            if user_title is not None:
                insight.user_title = user_title
            if user_topic_id is not None:
                chosen = session.get(TopicRecord, user_topic_id)
                if chosen is None or chosen.owner_user_id != owner_id:
                    raise ValueError("Topic not found")
                insight.user_topic_id = user_topic_id
                insight.filing_pending = 0
                insight.filed_by = "you"
                _remember_in(session, owner_id, f"You filed “{_clip_text(insight.user_title or insight.concise_title, 80)}” under {chosen.name}.",
                             kind="example", source_kind="correction", bot_key=chosen.bot_key,
                             item_ids=[item_id], status="confirmed")
            if user_priority is not None:
                insight.user_priority = user_priority
            if user_tags is not None:
                insight.user_tags_json = json.dumps(
                    user_tags, ensure_ascii=False
                )
        if needs_review is not None:
            insight.needs_review = 1 if needs_review else 0
        insight.updated_at = datetime.now(timezone.utc).isoformat()
        if item is not None and insight.user_title:
            item.title = insight.user_title
        session.commit()
        return _insight_to_dict(insight)


def list_relations_from_db(
    include_dismissed: bool = False,
) -> list[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        statement = (
            select(ItemRelationRecord)
            .join(InboxItemRecord, ItemRelationRecord.item_id_a == InboxItemRecord.id)
            .where(InboxItemRecord.owner_user_id == owner_id)
            .order_by(ItemRelationRecord.id.asc())
        )
        if not include_dismissed:
            statement = statement.where(ItemRelationRecord.dismissed == 0)
        rows = session.scalars(statement).all()
        return [
            {
                "id": row.id,
                "item_id_a": row.item_id_a,
                "item_id_b": row.item_id_b,
                "relation_type": row.relation_type,
                "score": float(row.score),
                "dismissed": bool(row.dismissed),
                "created_at": row.created_at,
            }
            for row in rows
        ]


def dismiss_relation_in_db(relation_id: int) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        row = session.get(ItemRelationRecord, relation_id)
        if row is None:
            return None
        anchor = session.get(InboxItemRecord, row.item_id_a)
        if anchor is None or anchor.owner_user_id != owner_id:
            return None
        row.dismissed = 1
        session.commit()
        return {
            "id": row.id,
            "item_id_a": row.item_id_a,
            "item_id_b": row.item_id_b,
            "relation_type": row.relation_type,
            "score": float(row.score),
            "dismissed": True,
            "created_at": row.created_at,
        }


def get_organization_dashboard() -> dict:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        session.commit()
        topics = list_topics_from_db()
        insights = {
            insight.item_id: _insight_to_dict(insight)
            for insight in session.scalars(
                select(ItemInsightRecord)
                .join(InboxItemRecord, ItemInsightRecord.item_id == InboxItemRecord.id)
                .where(InboxItemRecord.owner_user_id == owner_id)
            ).all()
        }
        completed_item_ids = set(
            session.scalars(
                select(TaskSourceItemRecord.item_id)
                .join(TaskRecord)
                .where(
                    TaskRecord.status == TASK_COMPLETED,
                    TaskRecord.owner_user_id == owner_id,
                )
            ).all()
        )
        items = [
            _item_to_dict(item)
            for item in session.scalars(
                select(InboxItemRecord)
                .where(InboxItemRecord.owner_user_id == owner_id)
                .order_by(InboxItemRecord.id.desc())
            ).all()
            if item.id not in completed_item_ids
        ]
        high_priority = []
        needs_review = []
        for item in items:
            insight = insights.get(item["id"])
            if insight is None:
                needs_review.append(
                    {
                        **item,
                        "reason": "Not yet organized",
                    }
                )
                continue
            card = {
                **item,
                "effective_title": insight["effective_title"],
                "effective_priority": insight["effective_priority"],
                "effective_topic_id": insight["effective_topic_id"],
                "rationale": insight["rationale"],
                "has_user_overrides": insight["has_user_overrides"],
            }
            if insight["effective_priority"] == "High":
                high_priority.append(card)
            if insight["needs_review"]:
                needs_review.append({**card, "reason": "Marked for review"})

        latest = get_latest_successful_analysis()
        if latest:
            latest = dict(latest)
            filtered_buckets = []
            for b in latest.get("buckets", []):
                active_notes = [
                    n for n in b.get("notes", [])
                    if n.get("id") not in completed_item_ids
                ]
                if active_notes:
                    filtered_buckets.append({**b, "notes": active_notes})
            latest["buckets"] = filtered_buckets
            pv = latest.get("priority_view", {})
            if isinstance(pv, dict):
                latest["priority_view"] = {
                    level: [
                        n for n in pv.get(level, [])
                        if n.get("id") not in completed_item_ids
                    ]
                    for level in ["High", "Medium", "Low"]
                }
            latest["todos"] = [
                t for t in latest.get("todos", [])
                if not (set(t.get("source_note_ids", [])) <= completed_item_ids)
            ]

        if latest and latest.get("is_stale"):
            for item in items:
                if item["id"] in insights:
                    needs_review.append(
                        {
                            **item,
                            "effective_title": insights[item["id"]][
                                "effective_title"
                            ],
                            "reason": "Analysis stale — re-analyze recommended",
                        }
                    )
                    break

        open_tasks = [
            t
            for t in list_tasks_from_db(TASK_OPEN)
            if not (set(t.get("source_item_ids", [])) & completed_item_ids)
        ]
        relations = [
            r
            for r in list_relations_from_db()
            if r["item_id_a"] not in completed_item_ids
            and r["item_id_b"] not in completed_item_ids
        ]
        return {
            "topics": topics,
            "high_priority": high_priority[:20],
            "open_tasks": open_tasks[:20],
            "recently_captured": items[:10],
            "needs_review": needs_review[:20],
            "related_items": relations[:20],
            "analysis": latest,
        }


# --- Captain's "Needs you" (change 013) ------------------------------------------------
# app/captain.py turns these facts into ranked cards. Plain data, no AI call.


def _note_title(item: InboxItemRecord, insight: Optional[ItemInsightRecord]) -> str:
    if insight is not None and (insight.user_title or insight.concise_title):
        return insight.user_title or insight.concise_title
    if item.title:
        return item.title
    first = (item.raw_text or item.user_context or item.source_url or item.original_filename or "").strip()
    return first.split("\n")[0][:120] or f"Note #{item.id}"


def captain_facts() -> dict:
    """What the signed-in user's "Needs you" list is worked out from: open
    tasks (and the latest edit that moved each unconfirmed date), notes with
    their filing, topics, and the card keys already answered."""
    from app.attention.dates import today_in_configured_tz

    owner_id = require_owner_id()
    with SessionLocal() as session:
        tasks = [
            _task_to_dict(session, task)
            for task in session.scalars(
                select(TaskRecord)
                .where(TaskRecord.owner_user_id == owner_id, TaskRecord.status == TASK_OPEN)
                .order_by(TaskRecord.id.asc())
            ).all()
        ]
        unconfirmed = {task["id"]: task for task in tasks if not task["timing_confirmed"]}
        moved: dict[int, Optional[dict]] = {}
        if unconfirmed:
            rows = session.scalars(
                select(TaskDateChangeRecord)
                .where(
                    TaskDateChangeRecord.owner_user_id == owner_id,
                    TaskDateChangeRecord.kind == "note_edit",
                    TaskDateChangeRecord.task_id.in_(list(unconfirmed)),
                )
                .order_by(TaskDateChangeRecord.id.desc())
            ).all()
            for row in rows:
                if row.task_id in moved:
                    continue
                task = unconfirmed[row.task_id]
                still = (task["due_on"] or task["suggested_due_on"]) == row.to_due_on and row.to_due_on
                moved[row.task_id] = {
                    "from_due_on": row.from_due_on,
                    "from_due_time": row.from_due_time,
                    "to_due_on": row.to_due_on,
                    "to_due_time": row.to_due_time,
                } if still else None

        items = session.scalars(
            select(InboxItemRecord)
            .where(InboxItemRecord.owner_user_id == owner_id)
            .order_by(InboxItemRecord.id.desc())
        ).all()
        insights = {
            row.item_id: row
            for row in session.scalars(
                select(ItemInsightRecord)
                .join(InboxItemRecord, InboxItemRecord.id == ItemInsightRecord.item_id)
                .where(InboxItemRecord.owner_user_id == owner_id)
            ).all()
        }
        topic_rows = session.scalars(
            select(TopicRecord).where(TopicRecord.owner_user_id == owner_id).order_by(TopicRecord.id.asc())
        ).all()
        topic_names = {topic.id: topic.name for topic in topic_rows}
        notes = []
        for item in items:
            insight = insights.get(item.id)
            topic_id = (insight.user_topic_id or insight.topic_id) if insight is not None else None
            notes.append({
                "id": item.id,
                "item_type": item.item_type,
                "title": _note_title(item, insight),
                "text": " ".join(part for part in (item.user_context, item.extracted_text or item.raw_text, item.title) if part),
                "source_url": item.source_url,
                "original_filename": item.original_filename,
                "processing_status": item.processing_status,
                "error_message": item.error_message,
                "created_at": item.created_at,
                "filed": insight is not None,
                "topic_id": topic_id,
                "topic_name": topic_names.get(topic_id),
                "pending": bool(insight.filing_pending) and insight.user_topic_id is None if insight is not None else False,
                "choices": json.loads(insight.filing_choices) if insight is not None and insight.filing_choices else [],
                "reason": insight.rationale if insight is not None else None,
                "needs_review": bool(insight.needs_review) if insight is not None else False,
            })
        topics = [
            {
                "id": topic.id,
                "name": topic.name,
                "description": topic.description,
                "bot_key": topic.bot_key,
                "parent_topic_id": topic.parent_topic_id,
                "archived": bool(topic.archived),
                "origin": topic.origin,
            }
            for topic in topic_rows
        ]
        answered = set(
            session.scalars(
                select(CaptainAnswerRecord.card_key).where(CaptainAnswerRecord.owner_user_id == owner_id)
            ).all()
        )
    return {
        "today": today_in_configured_tz().isoformat(),
        "ideas": list_ideas(status="waiting"),
        "plan_updates": list_plan_updates(),
        "proposals": list_topic_proposals(),
        "fact_checks": [fact for fact in list_memory(statuses=("suggested",)) if fact["source_kind"] == "weekly_review"],
        "tasks": tasks,
        "moved": {task_id: change for task_id, change in moved.items() if change},
        "notes": notes,
        "topics": topics,
        "answered": answered,
    }


def record_captain_answer(
    card_key: str,
    kind: str,
    answer: str,
    detail: Optional[dict] = None,
    item_id: Optional[int] = None,
    task_id: Optional[int] = None,
    topic_id: Optional[int] = None,
) -> None:
    """Keep your answer to a card (one row per card key, the latest wins)."""
    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        row = session.scalar(
            select(CaptainAnswerRecord).where(
                CaptainAnswerRecord.owner_user_id == owner_id,
                CaptainAnswerRecord.card_key == card_key,
            )
        )
        if row is None:
            row = CaptainAnswerRecord(owner_user_id=owner_id, card_key=card_key)
            session.add(row)
        row.kind = kind
        row.answer = answer
        row.detail = json.dumps(detail, ensure_ascii=False) if detail is not None else None
        row.item_id, row.task_id, row.topic_id = item_id, task_id, topic_id
        row.created_at = now
        session.commit()


def list_captain_answers() -> list[dict]:
    """Your answers to Captain's cards, newest first (memory examples, 016)."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        rows = session.scalars(
            select(CaptainAnswerRecord)
            .where(CaptainAnswerRecord.owner_user_id == owner_id)
            .order_by(CaptainAnswerRecord.id.desc())
        ).all()
        return [
            {
                "card_key": row.card_key,
                "kind": row.kind,
                "answer": row.answer,
                "detail": json.loads(row.detail) if row.detail else None,
                "item_id": row.item_id,
                "task_id": row.task_id,
                "topic_id": row.topic_id,
                "created_at": row.created_at,
            }
            for row in rows
        ]


def add_note_to_failed_capture(item_id: int, note: str) -> Optional[dict]:
    """Your own words for a capture that couldn't be read ("Add a note" on its
    Needs you card): saved as your note on the source, which then counts as
    read, so it can be filed from your words. None if it isn't yours."""
    cleaned = note.strip()
    if not cleaned:
        raise ValueError("Write a few words about what this was.")
    owner_id = require_owner_id()
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None or item.owner_user_id != owner_id:
            return None
        if item.processing_status != STATUS_FAILED:
            raise ValueError("Only a capture that couldn't be read takes a note here.")
        item.user_context = cleaned
        item.processing_status = STATUS_READY
        item.error_message = None
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


# --- Filing v2 helpers (change 014) ------------------------------------------------------


def filing_examples(item_ids: list[int]) -> dict[int, dict]:
    """How these notes are filed, for the filing call's "similar notes": the
    topic and life area, and whether you or the AI chose it. Yours only."""
    owner_id = require_owner_id()
    if not item_ids:
        return {}
    with SessionLocal() as session:
        rows = session.execute(
            select(InboxItemRecord, ItemInsightRecord)
            .join(ItemInsightRecord, ItemInsightRecord.item_id == InboxItemRecord.id)
            .where(InboxItemRecord.owner_user_id == owner_id, InboxItemRecord.id.in_(list(item_ids)))
        ).all()
        topics = {
            topic.id: topic
            for topic in session.scalars(select(TopicRecord).where(TopicRecord.owner_user_id == owner_id)).all()
        }
        examples = {}
        for item, insight in rows:
            topic_id = insight.user_topic_id if insight.user_topic_id is not None else insight.topic_id
            topic = topics.get(topic_id)
            if topic is None or topic.name.lower() == CATCH_ALL_TOPIC.lower() or insight.filing_pending:
                continue
            from app.sensitive import looks_secret, mask_secrets

            if looks_secret(item.raw_text) or looks_secret(item.user_context):
                continue  # a note holding a secret is never shown to the AI
            examples[item.id] = {
                "title": mask_secrets(insight.user_title or insight.concise_title),
                "topic": topic.name,
                "bot": topic.bot_key,
                "by": "you" if insight.user_topic_id is not None else "AI",
            }
        return examples


def list_resort_candidates() -> list[int]:
    """Notes "Re-sort everything" re-files: ready notes you didn't file yourself."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        mine = set(
            session.scalars(
                select(ItemInsightRecord.item_id)
                .join(InboxItemRecord, InboxItemRecord.id == ItemInsightRecord.item_id)
                .where(InboxItemRecord.owner_user_id == owner_id, ItemInsightRecord.user_topic_id.is_not(None))
            ).all()
        )
    return [note["id"] for note in list_notes_from_db() if note["id"] not in mine]


def notes_in_topic(topic_id: int) -> set[int]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        return set(
            session.scalars(
                select(ItemInsightRecord.item_id)
                .join(InboxItemRecord, InboxItemRecord.id == ItemInsightRecord.item_id)
                .where(
                    InboxItemRecord.owner_user_id == owner_id,
                    ((ItemInsightRecord.user_topic_id == topic_id)
                     | ((ItemInsightRecord.user_topic_id.is_(None)) & (ItemInsightRecord.topic_id == topic_id))),
                )
            ).all()
        )


def topic_assignments(item_ids: list[int]) -> dict[int, Optional[int]]:
    """The AI's topic for each note (what "Undo" puts back)."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        rows = session.execute(
            select(ItemInsightRecord.item_id, ItemInsightRecord.topic_id, ItemInsightRecord.filing_pending)
            .join(InboxItemRecord, InboxItemRecord.id == ItemInsightRecord.item_id)
            .where(InboxItemRecord.owner_user_id == owner_id, ItemInsightRecord.item_id.in_(list(item_ids or [-1])))
        ).all()
        return {item_id: topic_id for item_id, topic_id, _ in rows}


def undo_topic_moves(moves: list[dict]) -> int:
    """Put notes back in the topics they had before a new topic took them
    ("Moved 3 notes into Python · Undo"). Only your own notes and topics."""
    owner_id = require_owner_id()
    restored = 0
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        for move in moves:
            item = session.get(InboxItemRecord, int(move["item_id"]))
            insight = session.get(ItemInsightRecord, int(move["item_id"]))
            if item is None or item.owner_user_id != owner_id or insight is None:
                continue
            back = move.get("topic_id")
            if back is not None:
                topic = session.get(TopicRecord, int(back))
                if topic is None or topic.owner_user_id != owner_id:
                    continue
                insight.category = topic.name
            insight.topic_id = back
            insight.filing_pending = 0 if back is not None else insight.filing_pending
            insight.updated_at = now
            restored += 1
        session.commit()
    return restored


def retire_catch_all_if_empty() -> bool:
    """Remove the v1 catch-all "Personal / Reference" once no note is in it
    (change 014: there is no catch-all; unclear notes wait in Needs you)."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        topic = session.scalar(
            select(TopicRecord).where(
                TopicRecord.owner_user_id == owner_id, func.lower(TopicRecord.name) == CATCH_ALL_TOPIC.lower()
            )
        )
        if topic is None:
            return False
        still = session.scalar(
            select(func.count()).select_from(ItemInsightRecord).where(
                (ItemInsightRecord.topic_id == topic.id) | (ItemInsightRecord.user_topic_id == topic.id)
            )
        )
        children = session.scalar(
            select(func.count()).select_from(TopicRecord).where(TopicRecord.parent_topic_id == topic.id)
        )
        if still or children:
            return False
        session.delete(topic)
        session.commit()
        return True


# --- Thought-to-action: ideas that aren't tasks yet (change 014a) -------------------------
IDEA_INTENTS = ("tentative", "someday")


def _idea_to_dict(idea: "TaskIdeaRecord") -> dict:
    return {
        "id": idea.id, "item_id": idea.item_id, "text": idea.text, "timing_text": idea.timing_text,
        "intent": idea.intent, "status": idea.status, "task_id": idea.task_id, "created_at": idea.created_at,
    }


def _save_ideas(session, owner_id: int, ideas: Optional[dict], filed_items: set, now: str) -> None:
    """Replace the waiting ideas of the notes just filed. An idea you already
    added or dismissed isn't suggested again."""
    if not filed_items:
        return
    ideas = ideas or {}
    for item_id in filed_items:
        rows = session.scalars(
            select(TaskIdeaRecord).where(TaskIdeaRecord.owner_user_id == owner_id, TaskIdeaRecord.item_id == item_id)
        ).all()
        answered = {_normalize_task_text(row.text) for row in rows if row.status != "waiting"}
        for row in rows:
            if row.status == "waiting":
                session.delete(row)
        seen = set()
        for idea in ideas.get(item_id) or []:
            key = _normalize_task_text(idea["text"])
            if not key or key in answered or key in seen or idea.get("intent") not in IDEA_INTENTS:
                continue
            seen.add(key)
            session.add(TaskIdeaRecord(
                owner_user_id=owner_id, item_id=item_id, text=idea["text"][:500],
                timing_text=(idea.get("when") or None), intent=idea["intent"], status="waiting",
                created_at=now, updated_at=now,
            ))


def list_ideas(item_id: Optional[int] = None, status: Optional[str] = "waiting") -> list[dict]:
    """Your ideas (one note's, or all), waiting ones by default."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        query = select(TaskIdeaRecord).where(TaskIdeaRecord.owner_user_id == owner_id)
        if item_id is not None:
            query = query.where(TaskIdeaRecord.item_id == item_id)
        if status is not None:
            query = query.where(TaskIdeaRecord.status == status)
        return [_idea_to_dict(row) for row in session.scalars(query.order_by(TaskIdeaRecord.id.asc())).all()]


def add_idea_as_task(idea_id: int) -> Optional[dict]:
    """You said yes: the idea becomes a real task on its note, with its timing
    read as usual (a guess still waits for your OK). None if not yours."""
    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        idea = session.get(TaskIdeaRecord, idea_id)
        if idea is None or idea.owner_user_id != owner_id:
            return None
        if idea.status == "added" and idea.task_id:
            task = session.get(TaskRecord, idea.task_id)
            return _task_to_dict(session, task) if task else None
        insight = session.get(ItemInsightRecord, idea.item_id)
        task = TaskRecord(
            text=idea.text, priority=(insight.user_priority or insight.priority) if insight else "Medium",
            ai_timing_text=idea.timing_text, timing_confirmed=0, status=TASK_OPEN,
            dedup_key=_task_dedup_key([idea.item_id], idea.text), owner_user_id=owner_id,
            created_at=now, updated_at=now,
        )
        _apply_timing(task, idea.timing_text, _written_day(session, [idea.item_id]))
        session.add(task)
        session.flush()
        session.add(TaskSourceItemRecord(task_id=task.id, item_id=idea.item_id))
        idea.status, idea.task_id, idea.updated_at = "added", task.id, now
        session.commit()
        return _task_to_dict(session, task)


def dismiss_idea(idea_id: int) -> bool:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        idea = session.get(TaskIdeaRecord, idea_id)
        if idea is None or idea.owner_user_id != owner_id:
            return False
        idea.status, idea.updated_at = "dismissed", datetime.now(timezone.utc).isoformat()
        session.commit()
        return True


# --- The AI switch (change 025, decision Q) ------------------------------------------------


def _ai_switch_for_current_owner() -> bool:
    """On unless the signed-in user switched it off. No user (a script): on."""
    owner = _current_owner_id.get()
    if owner is None:
        return True
    with SessionLocal() as session:
        row = session.get(UserSettingsRecord, owner)
        return True if row is None else bool(row.ai_processing)


def _register_ai_switch() -> None:
    from app import llm

    llm.set_switch(_ai_switch_for_current_owner)


# --- Account deletion (change 025: the right to erasure) ----------------------------------


def erase_user(user_id: int) -> dict:
    """Delete everything of this user's: notes and files, tasks, topics,
    memory, settings, sessions, AI-call records, then the account. Child rows
    go first (foreign keys are enforced). Returns counts per table."""
    from sqlalchemy import delete as sql_delete, or_

    counts: dict[str, int] = {}
    with SessionLocal() as session:
        item_ids = list(session.scalars(select(InboxItemRecord.id).where(InboxItemRecord.owner_user_id == user_id)).all())
        task_ids = list(session.scalars(select(TaskRecord.id).where(TaskRecord.owner_user_id == user_id)).all())
        files = [path for path in session.scalars(select(InboxItemRecord.storage_path).where(
            InboxItemRecord.owner_user_id == user_id, InboxItemRecord.storage_path.is_not(None))).all() if path]
        for table in reversed(Base.metadata.sorted_tables):
            columns = table.c
            conditions = []
            if "owner_user_id" in columns:
                conditions.append(columns.owner_user_id == user_id)
            if "user_id" in columns:
                conditions.append(columns.user_id == user_id)
            if "item_id" in columns and item_ids:
                conditions.append(columns.item_id.in_(item_ids))
            if "task_id" in columns and task_ids:
                conditions.append(columns.task_id.in_(task_ids))
            for pair in ("item_id_a", "item_id_b"):
                if pair in columns and item_ids:
                    conditions.append(columns[pair].in_(item_ids))
            if table.name == "users":
                conditions = [columns.id == user_id]
            if not conditions:
                continue
            result = session.execute(sql_delete(table).where(or_(*conditions)))
            if result.rowcount:
                counts[table.name] = result.rowcount
        session.commit()
    for path in files:
        try:
            delete_stored_file(path)
        except Exception:
            logger.warning("Couldn't delete an uploaded file during account deletion")
    counts["files"] = len(files)
    return counts


# --- Onboarding, "Create New Life" (change 024) ----------------------------------------------
ONBOARDING_ROLES = {
    "student": "You are a student",
    "working": "You work",
    "both": "You study and work",
    "home": "You run a home",
}
ONBOARDING_FOCUS = {
    "studies": "College and studies", "work": "Work", "money": "Money and bills",
    "health": "Health and fitness", "family": "Family", "friends": "Friends",
    "hobbies": "Hobbies", "cooking": "Cooking", "travel": "Travel",
}


def onboarding_state(user_id: Optional[int] = None) -> dict:
    """Show the setup questions to a new account (no notes yet, not done or skipped)."""
    owner_id = user_id if user_id is not None else require_owner_id()
    settings = get_settings(owner_id)
    with SessionLocal() as session:
        has_notes = session.scalar(select(func.count()).select_from(InboxItemRecord).where(
            InboxItemRecord.owner_user_id == owner_id)) or 0
    return {"show": not settings["onboarding_done"] and not has_notes, "done": settings["onboarding_done"],
            "health_memory_consent": settings["health_memory_consent"], "ai_processing": settings["ai_processing"],
            "roles": list(ONBOARDING_ROLES), "focus": ONBOARDING_FOCUS}


def save_onboarding(answers: dict) -> dict:
    """Your answers become confirmed core-profile facts (016). Health consent
    is set first, so a fact about someone's medicines is kept only with it."""
    owner_id = require_owner_id()
    if answers.get("health_memory_consent") is not None:
        update_settings(owner_id, health_memory_consent=bool(answers["health_memory_consent"]))
    facts: list[tuple[str, Optional[str]]] = []
    role = answers.get("role")
    if role in ONBOARDING_ROLES:
        facts.append((ONBOARDING_ROLES[role], "learn" if role in ("student", "working", "both") else "money"))
    elif (answers.get("role_other") or "").strip():
        facts.append((f"You are {_clip_text(answers['role_other'], 80)}", None))
    if (answers.get("city") or "").strip():
        facts.append((f"You live in {_clip_text(answers['city'], 60)}", None))
    focus = [ONBOARDING_FOCUS[key] for key in answers.get("focus") or [] if key in ONBOARDING_FOCUS]
    if focus:
        listed = focus[0] if len(focus) == 1 else ", ".join(focus[:-1]) + " and " + focus[-1]
        facts.append((f"Your days are mostly about {listed}", None))
    if (answers.get("care") or "").strip():
        facts.append((f"You look after {_clip_text(answers['care'], 80)}", "people"))
    saved = []
    with SessionLocal() as session:
        for text, bot_key in facts:
            row = _remember_in(session, owner_id, text, kind="long_term", source_kind="onboarding",
                               bot_key=bot_key, status="confirmed", core=True)
            if row is not None:
                row.core_profile = 1
                session.flush()
                saved.append(_fact_to_dict(row))
        session.commit()
    update_settings(owner_id, onboarding_done=True)
    return {"facts": saved, "settings": get_settings(owner_id)}


# --- Settings (changes 016, 018, 020, 024, 025) ------------------------------------------
SETTINGS_FIELDS = ("health_memory_consent", "ai_processing", "catchup_day", "catchup_time",
                   "last_seen_at", "last_catchup_at", "last_weekly_review_at", "onboarding_done", "away_days")


def _settings_row(session, user_id: int) -> "UserSettingsRecord":
    row = session.get(UserSettingsRecord, user_id)
    if row is None:
        now = datetime.now(timezone.utc).isoformat()
        row = UserSettingsRecord(user_id=user_id, created_at=now, updated_at=now)
        session.add(row)
        session.flush()
    return row


def _settings_dict(row: "UserSettingsRecord") -> dict:
    return {
        "health_memory_consent": bool(row.health_memory_consent),
        "ai_processing": bool(row.ai_processing),
        "catchup_day": row.catchup_day,
        "catchup_time": row.catchup_time,
        "last_seen_at": row.last_seen_at,
        "last_catchup_at": row.last_catchup_at,
        "last_weekly_review_at": row.last_weekly_review_at,
        "onboarding_done": bool(row.onboarding_done),
        "away_days": row.away_days,
        "created_at": row.created_at,
    }


def get_settings(user_id: Optional[int] = None) -> dict:
    """The user's settings (made with the defaults on first use)."""
    owner_id = user_id if user_id is not None else require_owner_id()
    with SessionLocal() as session:
        row = _settings_row(session, owner_id)
        session.commit()
        return _settings_dict(row)


def update_settings(user_id: Optional[int] = None, **changes) -> dict:
    owner_id = user_id if user_id is not None else require_owner_id()
    with SessionLocal() as session:
        row = _settings_row(session, owner_id)
        for field, value in changes.items():
            if field not in SETTINGS_FIELDS:
                raise ValueError(f"Unknown setting {field}.")
            if field in ("health_memory_consent", "ai_processing", "onboarding_done"):
                value = 1 if value else 0
            setattr(row, field, value)
        row.updated_at = datetime.now(timezone.utc).isoformat()
        if "health_memory_consent" in changes and not changes["health_memory_consent"]:
            # Switching health memory off forgets what it held (deletable, design 8.5).
            for fact in session.scalars(select(MemoryFactRecord).where(
                    MemoryFactRecord.owner_user_id == owner_id, MemoryFactRecord.bot_key == "health",
                    MemoryFactRecord.status.in_(("suggested", "confirmed")))).all():
                fact.status, fact.text, fact.updated_at = "deleted", "", row.updated_at
        session.commit()
        return _settings_dict(row)


# --- Memory: what Life Inbox learns about you (change 016) --------------------------------
MEMORY_KINDS = ("long_term", "short_term", "example")
MEMORY_LIVE = ("suggested", "confirmed")
_MEDICAL_WORDS = re.compile(
    # Plurals too ("my parents' medicines"): a bare \b after the word missed them.
    r"\b(doctors?|dentists?|medicines?|medications?|pills?|tablets?|doses?|prescriptions?|pharmac(y|ies)|"
    r"hospitals?|clinics?|therap(y|ies|ists?)|diagnos\w*|allerg\w*|diabet\w*|thyroid|blood|surger(y|ies)|"
    r"symptom\w*|anxiety|depress\w*)\b", re.I)


def _clip_text(text: Optional[str], limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _fact_key(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return hashlib.sha256(" ".join(words).encode("utf-8")).hexdigest()


def _health_allowed(session, owner_id: int) -> bool:
    row = session.get(UserSettingsRecord, owner_id)
    return bool(row and row.health_memory_consent)


def _remember_in(
    session, owner_id: int, text: str, *, kind: str, source_kind: str, bot_key: Optional[str] = None,
    item_ids: Optional[list[int]] = None, status: str = "suggested", valid_until: Optional[str] = None,
    core: bool = False,
) -> Optional["MemoryFactRecord"]:
    """Keep a fact (inside an open session). Never a secret, never health
    without consent, never one you deleted. Seen again from another note, a
    suggested fact becomes confirmed."""
    from app.sensitive import looks_secret

    text = _clip_text(text, 200)
    if not text or kind not in MEMORY_KINDS or looks_secret(text):
        return None
    if item_ids:
        # A note holding a secret never becomes memory, not even its title: a
        # masked title can still carry part of it ("… code is 4821" after "PIN" was masked).
        for source in session.scalars(select(InboxItemRecord).where(InboxItemRecord.id.in_(list(item_ids)))).all():
            if _looks_secret(source):
                return None
    if (bot_key == "health" or _MEDICAL_WORDS.search(text)) and not _health_allowed(session, owner_id):
        return None
    if _MEDICAL_WORDS.search(text):
        bot_key = "health"
    now = datetime.now(timezone.utc).isoformat()
    key = _fact_key(text)
    row = session.scalar(select(MemoryFactRecord).where(
        MemoryFactRecord.owner_user_id == owner_id, MemoryFactRecord.text_key == key))
    items = sorted(set(item_ids or []))
    if row is not None:
        if row.status == "deleted":
            return None  # you deleted it: never suggested again
        known = set(json.loads(row.source_item_ids or "[]"))
        if items and not set(items) <= known:
            row.times_seen += 1
            row.source_item_ids = json.dumps(sorted(known | set(items)))
            if row.status == "suggested" and source_kind == "your_words":
                row.status = "confirmed"  # seen again
        if status == "confirmed" or row.status == "expired":
            row.status = status if status != "suggested" else row.status
        if valid_until:
            row.valid_until = valid_until
        row.updated_at = now
        return row
    row = MemoryFactRecord(
        owner_user_id=owner_id, bot_key=bot_key, kind=kind, text=text, text_key=key,
        source_item_ids=json.dumps(items), source_kind=source_kind, status=status, times_seen=1,
        valid_until=valid_until, core_profile=1 if core else 0, created_at=now, updated_at=now,
    )
    session.add(row)
    return row


def remember(text: str, **options) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        row = _remember_in(session, owner_id, text, **options)
        session.commit()
        return _fact_to_dict(row) if row is not None else None


def _fact_to_dict(row: "MemoryFactRecord") -> dict:
    return {
        "id": row.id, "bot_key": row.bot_key, "kind": row.kind, "text": row.text,
        "source_item_ids": json.loads(row.source_item_ids or "[]"), "source_kind": row.source_kind,
        "status": row.status, "times_seen": row.times_seen, "valid_until": row.valid_until,
        "core_profile": bool(row.core_profile), "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _expire_memory(session, owner_id: int) -> None:
    from app.attention.dates import today_in_configured_tz

    today = today_in_configured_tz().isoformat()
    for row in session.scalars(select(MemoryFactRecord).where(
            MemoryFactRecord.owner_user_id == owner_id, MemoryFactRecord.status.in_(MEMORY_LIVE),
            MemoryFactRecord.valid_until.is_not(None), MemoryFactRecord.valid_until < today)).all():
        row.status, row.updated_at = "expired", datetime.now(timezone.utc).isoformat()


def list_memory(bot: Optional[str] = None, statuses: tuple = MEMORY_LIVE, user_id: Optional[int] = None) -> list[dict]:
    """Your memory facts, newest first: one area's, or all ("" for Captain's)."""
    owner_id = user_id if user_id is not None else require_owner_id()
    with SessionLocal() as session:
        _expire_memory(session, owner_id)
        session.commit()
        query = select(MemoryFactRecord).where(
            MemoryFactRecord.owner_user_id == owner_id, MemoryFactRecord.status.in_(statuses))
        if bot == "":
            query = query.where(MemoryFactRecord.bot_key.is_(None))
        elif bot:
            query = query.where(MemoryFactRecord.bot_key == bot)
        if not _health_allowed(session, owner_id):
            query = query.where((MemoryFactRecord.bot_key.is_(None)) | (MemoryFactRecord.bot_key != "health"))
        return [_fact_to_dict(row) for row in session.scalars(query.order_by(MemoryFactRecord.id.desc())).all()]


def update_memory(fact_id: int, text: Optional[str] = None, status: Optional[str] = None,
                  core_profile: Optional[bool] = None) -> Optional[dict]:
    """Confirm, edit or mark a fact as part of your core profile."""
    from app.sensitive import looks_secret

    owner_id = require_owner_id()
    with SessionLocal() as session:
        row = session.get(MemoryFactRecord, fact_id)
        if row is None or row.owner_user_id != owner_id or row.status == "deleted":
            return None
        now = datetime.now(timezone.utc).isoformat()
        if text is not None:
            cleaned = _clip_text(text, 200)
            if not cleaned:
                raise ValueError("A fact needs some words.")
            if looks_secret(cleaned):
                raise ValueError("That looks like a secret; Life Inbox doesn't keep secrets in memory.")
            if _MEDICAL_WORDS.search(cleaned) and not _health_allowed(session, owner_id):
                raise ValueError("That's about health. Switch on health memory first (Health area).")
            key = _fact_key(cleaned)
            clash = session.scalar(select(MemoryFactRecord).where(
                MemoryFactRecord.owner_user_id == owner_id, MemoryFactRecord.text_key == key,
                MemoryFactRecord.id != fact_id))
            if clash is not None:
                raise ValueError("You already have that fact.")
            row.text, row.text_key, row.source_kind, row.status = cleaned, key, "you", "confirmed"
            if _MEDICAL_WORDS.search(cleaned):
                row.bot_key = "health"
        if status is not None:
            if status not in ("confirmed",):
                raise ValueError("A fact can only be confirmed here; delete it to forget it.")
            row.status = status
        if core_profile is not None:
            row.core_profile = 1 if core_profile else 0
        row.updated_at = now
        session.commit()
        return _fact_to_dict(row)


def delete_memory(fact_id: int) -> bool:
    """Forget a fact: its text is erased; it is never suggested again."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        row = session.get(MemoryFactRecord, fact_id)
        if row is None or row.owner_user_id != owner_id:
            return False
        row.status, row.text, row.updated_at = "deleted", "", datetime.now(timezone.utc).isoformat()
        session.commit()
        return True


# --- Weekly review, topic proposals, summaries, greeting (change 020) ----------------------


def list_user_ids() -> list[int]:
    with SessionLocal() as session:
        return list(session.scalars(select(UserRecord.id).order_by(UserRecord.id)).all())


def _masked_title(item, insight) -> str:
    from app.sensitive import mask_secrets

    return mask_secrets(_note_title(item, insight))


def review_facts(user_id: int) -> dict:
    """What the weekly review works from (read, after expiring past plans)."""
    from datetime import timedelta

    from app.sensitive import looks_secret, mask_secrets

    with SessionLocal() as session:
        _expire_memory(session, user_id)
        session.commit()
    memory = list_memory(statuses=("suggested", "confirmed"), user_id=user_id)
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with SessionLocal() as session:
        events = []
        for row in session.scalars(select(TaskEventRecord).where(
                TaskEventRecord.owner_user_id == user_id, TaskEventRecord.created_at >= since)
                .order_by(TaskEventRecord.id.asc())).all():
            task = session.get(TaskRecord, row.task_id)
            if task is None:
                continue
            what = {"done": "done", "dropped": "dropped", "someday": "moved to Someday", "kept": "kept for someday",
                    "reopened": "reopened"}.get(row.kind, f"moved to {row.to_due_on}" if row.to_due_on else row.kind)
            if row.reason:
                what += f" ({row.reason})"
            events.append({"id": row.id, "line": f"“{_clip_text(mask_secrets(task.text), 80)}”: {what}"})
        notes = []
        topics_by_id = {t.id: t for t in session.scalars(select(TopicRecord).where(TopicRecord.owner_user_id == user_id)).all()}
        for item in session.scalars(select(InboxItemRecord).where(InboxItemRecord.owner_user_id == user_id)
                                    .order_by(InboxItemRecord.id.desc()).limit(300)).all():
            insight = session.get(ItemInsightRecord, item.id)
            if insight is None:
                continue
            topic_id = insight.user_topic_id if insight.user_topic_id is not None else insight.topic_id
            topic = topics_by_id.get(topic_id)
            secret = any(looks_secret(value) for value in (item.raw_text, item.user_context))
            own = item.user_context or (item.raw_text if item.item_type == "text" else "")
            notes.append({"id": item.id, "title": _masked_title(item, insight), "secret": secret,
                          "text": "" if secret else f"{_note_title(item, insight)} {(own or '')[:300]}",
                          "bot_key": topic.bot_key if topic else None, "topic_id": topic_id})
        topics = [_topic_to_dict(t) for t in topics_by_id.values()]
        proposals = session.scalars(select(TopicProposalRecord).where(TopicProposalRecord.owner_user_id == user_id)).all()
    return {
        "memory": memory, "events": events, "notes": notes, "topics": topics,
        "never": {p.signature for p in proposals if p.status == "never"},
        "pending_signatures": {p.signature for p in proposals if p.status in ("pending", "created", "declined")},
        "pending": [{"name": p.name} for p in proposals if p.status == "pending"],
    }


def save_review(user_id: int, checked: dict) -> dict:
    """Apply the weekly review's checked answer."""
    now = datetime.now(timezone.utc).isoformat()
    counts = {"merged": 0, "trimmed": 0, "new_facts": 0, "proposals": 0}
    with SessionLocal() as session:
        def mine(fact_id):
            row = session.get(MemoryFactRecord, fact_id)
            return row if row is not None and row.owner_user_id == user_id and row.status in MEMORY_LIVE else None

        for merge in checked.get("merge") or []:
            keep = mine(merge["keep"])
            if keep is None:
                continue
            sources = set(json.loads(keep.source_item_ids or "[]"))
            for drop_id in merge["drop"]:
                drop = mine(drop_id)
                if drop is None:
                    continue
                sources |= set(json.loads(drop.source_item_ids or "[]"))
                keep.times_seen += drop.times_seen
                drop.status, drop.updated_at = "expired", now
                counts["merged"] += 1
            keep.source_item_ids, keep.updated_at = json.dumps(sorted(sources)), now
        for fact_id in checked.get("trim") or []:
            row = mine(fact_id)
            if row is not None:
                row.status, row.updated_at = "expired", now
                counts["trimmed"] += 1
        for fact in checked.get("new_facts") or []:
            row = _remember_in(session, user_id, fact["text"], kind="long_term", source_kind="weekly_review",
                               item_ids=fact.get("item_ids") or [], status="suggested")
            if row is not None:
                counts["new_facts"] += 1
        for proposal in checked.get("proposals") or []:
            seen = session.scalar(select(TopicProposalRecord).where(
                TopicProposalRecord.owner_user_id == user_id, TopicProposalRecord.signature == proposal["signature"]))
            if seen is not None:
                continue
            session.add(TopicProposalRecord(
                owner_user_id=user_id, bot_key=proposal["bot_key"], name=proposal["name"],
                description=proposal.get("description"), parent_topic_id=proposal["parent_topic_id"],
                item_ids=json.dumps(proposal["item_ids"]), signature=proposal["signature"], status="pending",
                created_at=now, updated_at=now))
            counts["proposals"] += 1
        session.commit()
    return counts


def list_topic_proposals(status: str = "pending") -> list[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        found = []
        for row in session.scalars(select(TopicProposalRecord).where(
                TopicProposalRecord.owner_user_id == owner_id, TopicProposalRecord.status == status)
                .order_by(TopicProposalRecord.id.asc())).all():
            parent = session.get(TopicRecord, row.parent_topic_id) if row.parent_topic_id else None
            titles = []
            for item_id in json.loads(row.item_ids or "[]"):
                item = session.get(InboxItemRecord, item_id)
                if item is not None and item.owner_user_id == owner_id:
                    titles.append(_masked_title(item, session.get(ItemInsightRecord, item_id)))
            if len(titles) < 3:
                continue  # its notes were deleted: it no longer has 3 to stand on
            found.append({"id": row.id, "bot_key": row.bot_key, "name": row.name, "description": row.description,
                          "parent_topic_id": row.parent_topic_id, "parent_name": parent.name if parent else None,
                          "item_ids": json.loads(row.item_ids), "titles": titles})
        return found


def create_topic_from_proposal(proposal_id: int, name: Optional[str] = None) -> Optional[dict]:
    """You said Create it (or Rename): the topic is made under its parent,
    the notes move in (not the ones you placed yourself), and its history is kept."""
    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        row = session.get(TopicProposalRecord, proposal_id)
        if row is None or row.owner_user_id != owner_id or row.status != "pending":
            return None
        title = " ".join((name or row.name).split())[:60]
        if not title:
            raise ValueError("The topic needs a name.")
        clash = session.scalar(select(TopicRecord).where(
            TopicRecord.owner_user_id == owner_id, func.lower(TopicRecord.name) == title.lower()))
        if clash is not None:
            raise ValueError(f"You already have a topic called “{clash.name}”.")
        parent = session.get(TopicRecord, row.parent_topic_id) if row.parent_topic_id else None
        topic = TopicRecord(name=title, description=row.description, owner_user_id=owner_id, created_at=now,
                            updated_at=now, archived=0, parent_topic_id=parent.id if parent else None,
                            bot_key=row.bot_key, origin=ORIGIN_USER, proposed_by=row.bot_key,
                            evidence_item_ids=row.item_ids, approved_at=now)
        session.add(topic)
        session.flush()
        for item_id in json.loads(row.item_ids or "[]"):
            insight = session.get(ItemInsightRecord, item_id)
            item = session.get(InboxItemRecord, item_id)
            if insight is None or item is None or item.owner_user_id != owner_id or insight.user_topic_id is not None:
                continue
            insight.topic_id, insight.category, insight.filing_pending, insight.updated_at = topic.id, title, 0, now
        row.status, row.topic_id, row.updated_at = "created", topic.id, now
        session.commit()
        return _topic_to_dict(topic)


def decline_proposal(proposal_id: int, never: bool = False) -> bool:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        row = session.get(TopicProposalRecord, proposal_id)
        if row is None or row.owner_user_id != owner_id or row.status != "pending":
            return False
        row.status, row.updated_at = ("never" if never else "declined"), datetime.now(timezone.utc).isoformat()
        session.commit()
        return True


def bot_area(bot_key: str, user_id: int) -> dict:
    """An area's notes (newest first, secrets left out) and open tasks, for its summary."""
    from app.sensitive import looks_secret, mask_secrets

    with SessionLocal() as session:
        topics = {t.id for t in session.scalars(select(TopicRecord).where(
            TopicRecord.owner_user_id == user_id, TopicRecord.bot_key == bot_key)).all()}
        notes = []
        for item in session.scalars(select(InboxItemRecord).where(InboxItemRecord.owner_user_id == user_id)
                                    .order_by(InboxItemRecord.id.desc())).all():
            insight = session.get(ItemInsightRecord, item.id)
            topic_id = (insight.user_topic_id if insight.user_topic_id is not None else insight.topic_id) if insight else None
            if topic_id not in topics or any(looks_secret(v) for v in (item.raw_text, item.user_context)):
                continue
            notes.append({"id": item.id, "title": _note_title(item, insight), "updated": insight.updated_at})
        tasks = []
        for task in session.scalars(select(TaskRecord).where(
                TaskRecord.owner_user_id == user_id, TaskRecord.status == TASK_OPEN).order_by(TaskRecord.id)).all():
            sources = session.scalars(select(TaskSourceItemRecord.item_id).where(TaskSourceItemRecord.task_id == task.id)).all()
            area, _ = _source_context(session, sources[0] if sources else None)
            if area == bot_key:
                tasks.append({"id": task.id, "text": mask_secrets(task.text), "day": task.due_on or task.suggested_due_on})
    return {"bot_key": bot_key, "notes": notes, "tasks": tasks}


def get_bot_summary(bot_key: str, user_id: int) -> Optional[dict]:
    with SessionLocal() as session:
        row = session.get(BotSummaryRecord, (user_id, bot_key))
        return {"summary": row.summary, "data_key": row.data_key, "created_at": row.created_at} if row else None


def save_bot_summary(bot_key: str, summary: str, data_key: str, user_id: int) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        row = session.get(BotSummaryRecord, (user_id, bot_key)) or BotSummaryRecord(owner_user_id=user_id, bot_key=bot_key)
        row.summary, row.data_key, row.created_at = summary, data_key, now
        session.merge(row)
        session.commit()


def get_greeting(day: str, user_id: int) -> Optional[str]:
    with SessionLocal() as session:
        row = session.get(GreetingRecord, (user_id, day))
        return row.text if row else None


def save_greeting(day: str, text: str, user_id: int) -> None:
    with SessionLocal() as session:
        if session.get(GreetingRecord, (user_id, day)) is None:
            session.add(GreetingRecord(owner_user_id=user_id, day=day, text=text,
                                       created_at=datetime.now(timezone.utc).isoformat()))
            session.commit()


def greeting_facts(user_id: int) -> dict:
    """What Captain's greeting may mention: Needs you, today's and the next tasks."""
    import app.captain as captain
    from app.attention.dates import today_in_configured_tz
    from app.sensitive import mask_secrets

    today = today_in_configured_tz()
    needs = len(captain.build_cards(captain_facts()))
    with SessionLocal() as session:
        rows = session.scalars(select(TaskRecord).where(
            TaskRecord.owner_user_id == user_id, TaskRecord.status == TASK_OPEN, TaskRecord.due_on.is_not(None),
            TaskRecord.due_on >= today.isoformat()).order_by(TaskRecord.due_on, TaskRecord.id).limit(6)).all()
        due_today = [mask_secrets(t.text)[:80] for t in rows if t.due_on == today.isoformat()]
        soon = [f"{mask_secrets(t.text)[:80]} ({t.due_on})" for t in rows if t.due_on != today.isoformat()]
    return {"weekday": today.strftime("%A"), "needs": needs, "today": due_today, "soon": soon}


# --- Scout (change 018) ------------------------------------------------------------------


def scout_facts(user_id: Optional[int] = None) -> dict:
    """What Scout works from: your settings, your open tasks, and the
    questions you already answered."""
    owner_id = user_id if user_id is not None else require_owner_id()
    settings = get_settings(owner_id)
    with SessionLocal() as session:
        tasks = [_task_to_dict(session, task) for task in session.scalars(
            select(TaskRecord).where(TaskRecord.owner_user_id == owner_id, TaskRecord.status == TASK_OPEN)
            .order_by(TaskRecord.id.asc())).all()]
        answered = set(session.scalars(select(CaptainAnswerRecord.card_key).where(
            CaptainAnswerRecord.owner_user_id == owner_id, CaptainAnswerRecord.kind == "scout")).all())
    return {"settings": settings, "tasks": tasks, "answered": answered}


def record_task_event(task_id: int, kind: str, by: str = "you", reason: Optional[str] = None,
                      from_due_on: Optional[str] = None, to_due_on: Optional[str] = None) -> None:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return
        session.add(TaskEventRecord(owner_user_id=owner_id, task_id=task_id, kind=kind, by=by, reason=reason,
                                    from_due_on=from_due_on, to_due_on=to_due_on,
                                    created_at=datetime.now(timezone.utc).isoformat()))
        session.commit()


def set_task_someday(task_ids: list[int], on: bool, by: Optional[str] = "you") -> int:
    """Move tasks to Someday (their dates go: off the calendar, Timeline and
    reminders), or back. `by=None` only refreshes when they were last looked at."""
    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    moved = 0
    with SessionLocal() as session:
        for task_id in task_ids:
            task = session.get(TaskRecord, task_id)
            if task is None or task.owner_user_id != owner_id or task.status != TASK_OPEN:
                continue
            if on:
                if by is not None and not task.someday:
                    session.add(TaskEventRecord(owner_user_id=owner_id, task_id=task.id, kind="someday", by=by,
                                                from_due_on=task.due_on, created_at=now))
                    task.due_on = task.due_time = task.suggested_due_on = task.suggested_due_time = None
                    task.timing_confirmed, task.due_confidence, task.timing_text = 0, None, None
                    task.snoozed_until = None
                task.someday, task.someday_since = 1, now
            else:
                task.someday, task.someday_since = 0, None
            task.updated_at = now
            moved += 1
        session.commit()
    return moved


def memory_for_filing(user_id: Optional[int] = None) -> dict:
    """What the filing call may be shown (017): your next plans, and your
    confirmed facts (suggested ones wait until you or a second note confirm)."""
    return {"plans": upcoming_plans(user_id=user_id),
            "facts": list_memory(statuses=("confirmed",), user_id=user_id)}


# --- Plan updates: a note that moves a plan you have (change 017) ---------------------------


def _save_plan_updates(session, owner_id: int, updates: Optional[dict], now: str) -> None:
    for item_id, update in (updates or {}).items():
        task = session.get(TaskRecord, update.get("task_id"))
        if task is None or task.owner_user_id != owner_id or task.status != TASK_OPEN:
            continue
        waiting = session.scalar(select(PlanUpdateRecord).where(
            PlanUpdateRecord.owner_user_id == owner_id, PlanUpdateRecord.item_id == item_id,
            PlanUpdateRecord.task_id == task.id, PlanUpdateRecord.status == "waiting"))
        row = waiting or PlanUpdateRecord(owner_user_id=owner_id, item_id=item_id, task_id=task.id,
                                          status="waiting", created_at=now)
        row.task_text = task.text
        row.new_task_text = _clip_text(update.get("new_task_text") or task.text, 300)
        row.new_timing_text = update.get("when") or None
        row.new_due_on, row.new_due_time, row.updated_at = update["date"], update.get("time") or None, now
        if waiting is None:
            session.add(row)


def list_plan_updates(status: str = "waiting") -> list[dict]:
    """Your plan updates, with each plan's current day (gone or done plans skipped)."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        rows = session.scalars(select(PlanUpdateRecord).where(
            PlanUpdateRecord.owner_user_id == owner_id, PlanUpdateRecord.status == status)
            .order_by(PlanUpdateRecord.id.asc())).all()
        found = []
        for row in rows:
            task = session.get(TaskRecord, row.task_id)
            if task is None or task.owner_user_id != owner_id or task.status != TASK_OPEN:
                continue
            if task.due_on == row.new_due_on and (task.due_time or None) == (row.new_due_time or None):
                continue  # already on the new day
            found.append({"id": row.id, "item_id": row.item_id, "task_id": row.task_id, "task_text": task.text,
                          "from_due_on": task.due_on, "from_due_time": task.due_time,
                          "new_task_text": row.new_task_text, "new_due_on": row.new_due_on,
                          "new_due_time": row.new_due_time})
        return found


def apply_plan_update(update_id: int) -> Optional[dict]:
    """Yes, move it: the plan takes the new day (as yours), and the note becomes one of its sources."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        row = session.get(PlanUpdateRecord, update_id)
        if row is None or row.owner_user_id != owner_id or row.status != "waiting":
            return None
        task_id, item_id, due_on, due_time = row.task_id, row.item_id, row.new_due_on, row.new_due_time
    task = set_task_date(task_id, due_on, due_time)
    if task is None:
        return None
    with SessionLocal() as session:
        row = session.get(PlanUpdateRecord, update_id)
        linked = session.scalar(select(TaskSourceItemRecord).where(
            TaskSourceItemRecord.task_id == task_id, TaskSourceItemRecord.item_id == item_id))
        if linked is None and session.get(InboxItemRecord, item_id) is not None:
            session.add(TaskSourceItemRecord(task_id=task_id, item_id=item_id))
        row.status, row.updated_at = "applied", datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, session.get(TaskRecord, task_id))


def decline_plan_update(update_id: int) -> Optional[dict]:
    """No, it's a different one: the note's own task is made, on its own day."""
    owner_id = require_owner_id()
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        row = session.get(PlanUpdateRecord, update_id)
        if row is None or row.owner_user_id != owner_id or row.status != "waiting":
            return None
        insight = session.get(ItemInsightRecord, row.item_id)
        task = TaskRecord(
            text=row.new_task_text, priority=(insight.user_priority or insight.priority) if insight else "Medium",
            ai_timing_text=row.new_timing_text, timing_confirmed=0, status=TASK_OPEN,
            dedup_key=_task_dedup_key([row.item_id], row.new_task_text), owner_user_id=owner_id,
            created_at=now, updated_at=now,
        )
        _apply_timing(task, row.new_timing_text, _written_day(session, [row.item_id]))
        if not task.due_on and not task.suggested_due_on and row.new_due_on:
            task.suggested_due_on, task.suggested_due_time = row.new_due_on, row.new_due_time
            task.due_confidence = "suggested"
        session.add(task)
        session.flush()
        session.add(TaskSourceItemRecord(task_id=task.id, item_id=row.item_id))
        row.status, row.updated_at = "declined", now
        session.commit()
        return _task_to_dict(session, task)


def upcoming_plans(days: int = 14, limit: int = 8, user_id: Optional[int] = None) -> list[dict]:
    """Short-term memory: your dated open tasks in the next `days` (from your tasks)."""
    from datetime import timedelta

    from app.attention.dates import today_in_configured_tz

    owner_id = user_id if user_id is not None else require_owner_id()
    today = today_in_configured_tz()
    end = (today + timedelta(days=days)).isoformat()
    with SessionLocal() as session:
        rows = session.scalars(select(TaskRecord).where(
            TaskRecord.owner_user_id == owner_id, TaskRecord.status == TASK_OPEN,
            TaskRecord.due_on.is_not(None), TaskRecord.due_on >= today.isoformat(), TaskRecord.due_on <= end,
        ).order_by(TaskRecord.due_on.asc(), TaskRecord.id.asc()).limit(limit)).all()
        return [{"task_id": row.id, "text": row.text, "due_on": row.due_on, "due_time": row.due_time,
                 "confirmed": bool(row.timing_confirmed) or row.due_confidence == DATE_FROM_NOTE} for row in rows]


# Every AI call checks the signed-in user's switch (change 025).
_register_ai_switch()
