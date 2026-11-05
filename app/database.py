import hashlib
import json
import os
import re
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
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
    owner_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=True)


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
        UniqueConstraint("dedup_key"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    priority = Column(Text, nullable=False)
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


DEFAULT_TOPIC_NAMES = (
    "Work",
    "Money & Admin",
    "Learning",
    "Shopping & Errands",
    "Health",
    "Travel",
    "Ideas",
    "People",
    "Personal / Reference",
)


def set_current_owner_id(owner_user_id: Optional[int]) -> None:
    _current_owner_id.set(owner_user_id)


def get_current_owner_id() -> Optional[int]:
    return _current_owner_id.get()


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
                description=None,
                owner_user_id=owner,
                created_at=now,
                updated_at=now,
                archived=0,
            )
        )
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
) -> list[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        statement = select(InboxItemRecord).where(
            InboxItemRecord.owner_user_id == owner_id
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

        statement = statement.order_by(InboxItemRecord.id.asc()).offset(offset)
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

        item.raw_text = raw_text
        item.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _item_to_dict(item)


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
        text = item.get("extracted_text") or item.get("raw_text")
        if not text:
            continue
        notes.append(
            {
                "id": item["id"],
                "text": text,
                "created_at": item["created_at"],
            }
        )
    return notes


def get_note_from_db(item_id: int) -> Optional[dict]:
    item = get_item_from_db(item_id)
    if (
        not item
        or item["item_type"] not in ANALYZABLE_TYPES
        or item["processing_status"] not in ANALYZABLE_STATUSES
    ):
        return None
    text = item.get("extracted_text") or item.get("raw_text")
    if not text:
        return None
    return {
        "id": item["id"],
        "text": text,
        "created_at": item["created_at"],
    }


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


def _topic_id_by_name(session, name: str) -> Optional[int]:
    owner_id = require_owner_id()
    ensure_default_topics(session, owner_user_id=owner_id)
    topic = session.scalars(
        select(TopicRecord).where(
            TopicRecord.name == name,
            TopicRecord.owner_user_id == owner_id,
        )
    ).first()
    if topic is not None:
        return topic.id
    now = datetime.now(timezone.utc).isoformat()
    topic = TopicRecord(
        name=name,
        description="Created from AI organization",
        owner_user_id=owner_id,
        created_at=now,
        updated_at=now,
        archived=0,
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


def complete_analysis_run(
    run_id: int, result: dict, merge_single: bool = False
) -> dict:
    completed_at = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        run = session.get(AnalysisRunRecord, run_id)
        if run is None or run.status != ANALYSIS_RUNNING:
            raise ValueError("Analysis run is not available for completion")

        ensure_default_topics(session, owner_user_id=require_owner_id())

        for bucket in result["buckets"]:
            topic_id = _topic_id_by_name(session, bucket["name"])
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

            if task is None:
                parsed_timing = parse_timing_phrase(todo.get("when"))
                task = TaskRecord(
                    text=todo["task"],
                    priority=todo["priority"],
                    timing_text=todo["when"],
                    ai_timing_text=todo["when"],
                    timing_confirmed=0,
                    due_on=parsed_timing.normalized_iso,
                    due_time=normalize_time_of_day(todo.get("when")),
                    due_confidence=parsed_timing.confidence,
                    status=TASK_OPEN,
                    dedup_key=dedup_key,
                    owner_user_id=owner_id,
                    created_at=completed_at,
                    updated_at=completed_at,
                )
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
                    task.text = todo["task"]
                    task.priority = todo["priority"]
                task.ai_timing_text = todo["when"]
                if not task.timing_confirmed:
                    task.timing_text = todo["when"]
                    parsed_timing = parse_timing_phrase(todo.get("when"))
                    task.due_on = parsed_timing.normalized_iso
                    task.due_time = normalize_time_of_day(todo.get("when"))
                    task.due_confidence = parsed_timing.confidence
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


def _ensure_task_due_fields(task: TaskRecord) -> None:
    """Normalize due_on from timing_text when missing."""
    from app.attention.dates import normalize_time_of_day, parse_timing_phrase

    if task.due_time is None:
        task.due_time = normalize_time_of_day(task.timing_text)
    if task.due_on and task.due_confidence:
        return
    parsed = parse_timing_phrase(task.timing_text)
    task.due_on = parsed.normalized_iso
    task.due_confidence = parsed.confidence
    task.due_time = task.due_time or normalize_time_of_day(task.timing_text)


def _task_to_dict(session, task: TaskRecord) -> dict:
    _ensure_task_due_fields(task)
    source_item_ids = session.scalars(
        select(TaskSourceItemRecord.item_id)
        .where(TaskSourceItemRecord.task_id == task.id)
        .order_by(TaskSourceItemRecord.item_id.asc())
    ).all()
    return {
        "id": task.id,
        "text": task.text,
        "priority": task.priority,
        "timing_text": task.timing_text,
        "ai_timing_text": task.ai_timing_text,
        "timing_confirmed": bool(task.timing_confirmed),
        "due_on": task.due_on,
        "due_time": task.due_time,
        "due_confidence": task.due_confidence,
        "snoozed_until": task.snoozed_until,
        "reminder_at": task.reminder_at,
        "status": task.status,
        "source_item_ids": list(source_item_ids),
        "created_at": task.created_at,
        "updated_at": task.updated_at,
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
            due_confidence="high" if due_on else None,
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


def list_tasks_from_db(status_filter: str = TASK_OPEN) -> list[dict]:
    if status_filter not in TASK_STATUSES | {"all"}:
        raise ValueError("Unsupported task status")

    owner_id = require_owner_id()
    with SessionLocal() as session:
        statement = (
            select(TaskRecord)
            .where(TaskRecord.owner_user_id == owner_id)
            .order_by(TaskRecord.id.asc())
        )
        if status_filter != "all":
            statement = statement.where(TaskRecord.status == status_filter)
        tasks = session.scalars(statement).all()
        return [_task_to_dict(session, task) for task in tasks]


def set_task_status(task_id: int, task_status: str) -> Optional[dict]:
    if task_status not in TASK_STATUSES:
        raise ValueError("Unsupported task status")

    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        if task.status != task_status:
            task.status = task_status
            task.updated_at = datetime.now(timezone.utc).isoformat()
            session.commit()
        return _task_to_dict(session, task)


def list_calendar_events_from_db(start_date: str, end_date: str) -> list[dict]:
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
            needs_confirmation = (not bool(task.timing_confirmed)) and parsed.needs_confirmation

            events.append(
                {
                    "id": task.id,
                    "title": task.text,
                    "event_date": task.due_on,
                    "priority": task.priority,
                    "status": task.status,
                    "timing_text": task.timing_text,
                    "time_of_day": parsed.time_of_day,
                    "timing_confirmed": bool(task.timing_confirmed),
                    "due_confidence": task.due_confidence or parsed.confidence,
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


def add_image_item_to_db(
    original_filename: str,
    storage_path: str,
    mime_type: str,
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


def add_url_item_to_db(url: str) -> dict:
    """Persist URL first (captured), then return the row for processing."""
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        item = InboxItemRecord(
            item_type=URL_ITEM_TYPE,
            source_url=url,
            processing_status=STATUS_CAPTURED,
            owner_user_id=require_owner_id(),
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


def complete_url_item_processing(
    item_id: int,
    *,
    title: str,
    raw_text: str,
    mime_type: Optional[str],
    final_url: Optional[str] = None,
) -> Optional[dict]:
    with SessionLocal() as session:
        item = session.get(InboxItemRecord, item_id)
        if item is None:
            return None
        item.title = title
        item.raw_text = raw_text
        item.extracted_text = raw_text
        item.mime_type = mime_type
        if final_url:
            item.source_url = final_url
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
        if timing_text is not None:
            task.timing_text = timing_text
        parsed = parse_timing_phrase(task.timing_text)
        task.due_on = parsed.normalized_iso
        task.due_time = normalize_time_of_day(task.timing_text)
        task.due_confidence = "high" if parsed.due_date else parsed.confidence
        task.timing_confirmed = 1
        task.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, task)


def update_task_in_db(
    task_id: int,
    *,
    text: Optional[str] = None,
    priority: Optional[str] = None,
    due_on: Optional[str] = None,
    clear_due: bool = False,
) -> Optional[dict]:
    """Edit a task the user owns. A new date counts as user-confirmed."""
    owner_id = require_owner_id()
    with SessionLocal() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.owner_user_id != owner_id:
            return None
        if text is not None:
            cleaned = text.strip()
            if not cleaned:
                raise ValueError("Task text cannot be empty.")
            task.text = cleaned
            task.user_edited = 1
        if priority is not None:
            task.priority = priority
            task.user_edited = 1
        if clear_due:
            task.timing_text = None
            task.due_on = None
            task.due_time = None
            task.due_confidence = None
            task.timing_confirmed = 0
        elif due_on is not None:
            task.timing_text = due_on
            task.due_on = due_on
            task.due_time = None
            task.due_confidence = "high"
            task.timing_confirmed = 1
        task.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _task_to_dict(session, task)


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
        return [
            {
                "user_id": row.user_id,
                "daily_digest_time": row.daily_digest_time,
                "timezone": row.timezone,
                "include_unscheduled_prompt": bool(
                    row.include_unscheduled_prompt
                ),
            }
            for row in rows
        ]


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
                    "priority": task.priority,
                    "due_on": task.due_on,
                    "due_time": task.due_time,
                    "timing_text": task.timing_text,
                    "timing_confirmed": bool(task.timing_confirmed),
                    "due_confidence": task.due_confidence,
                    "snoozed_until": task.snoozed_until,
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


def _topic_to_dict(topic: TopicRecord, item_count: int = 0) -> dict:
    return {
        "id": topic.id,
        "name": topic.name,
        "description": topic.description,
        "archived": bool(topic.archived),
        "item_count": item_count,
        "created_at": topic.created_at,
        "updated_at": topic.updated_at,
    }


def list_topics_from_db(include_archived: bool = False) -> list[dict]:
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
        topics = session.scalars(statement).all()
        counts = {}
        # Completed notes leave the active views, so they don't count here.
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
        return [
            _topic_to_dict(topic, counts.get(topic.id, 0)) for topic in topics
        ]


def create_topic_in_db(name: str, description: Optional[str] = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    owner_id = require_owner_id()
    with SessionLocal() as session:
        ensure_default_topics(session, owner_user_id=owner_id)
        existing = session.scalars(
            select(TopicRecord).where(
                TopicRecord.name == name,
                TopicRecord.owner_user_id == owner_id,
            )
        ).first()
        if existing is not None:
            if existing.archived:
                existing.archived = 0
                existing.description = description
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
        )
        session.add(topic)
        session.commit()
        return _topic_to_dict(topic)


def update_topic_in_db(
    topic_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    archived: Optional[bool] = None,
) -> Optional[dict]:
    owner_id = require_owner_id()
    with SessionLocal() as session:
        topic = session.get(TopicRecord, topic_id)
        if topic is not None and topic.owner_user_id != owner_id:
            return None
        if topic is None:
            return None
        if name is not None:
            topic.name = name
        if description is not None:
            topic.description = description
        if archived is not None:
            topic.archived = 1 if archived else 0
        topic.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _topic_to_dict(topic)


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


def _insight_to_dict(insight: ItemInsightRecord) -> dict:
    effective_title = insight.user_title or insight.concise_title
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
                if session.get(TopicRecord, user_topic_id) is None:
                    raise ValueError("Topic not found")
                insight.user_topic_id = user_topic_id
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
