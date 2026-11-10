import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def alembic_config(database_path: Path) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    return config


def test_upgrade_creates_inbox_items_in_empty_database(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "empty.db"

    command.upgrade(alembic_config(database_path), "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        inspector = inspect(engine)
        assert {
            "alembic_version",
            "analysis_runs",
            "inbox_items",
            "item_insights",
            "item_relations",
            "notes",
            "task_source_items",
            "tasks",
            "topics",
            "calendar_action_receipts",
            "notification_preferences",
            "notification_deliveries",
            "push_subscriptions",
            "task_date_changes",
            "users",
            "ai_calls",
            "memory_facts",
            "user_settings",
            "plan_updates",
            "task_events",
            "topic_proposals",
            "bot_summaries",
            "greetings",
        } <= set(inspector.get_table_names())
        # The AI call log keeps sizes and outcomes only, never prompt or answer text.
        assert {column["name"] for column in inspector.get_columns("ai_calls")} == {
            "id",
            "owner_user_id",
            "action",
            "model",
            "outcome",
            "attempt",
            "status_code",
            "input_size",
            "output_size",
            "duration_ms",
            "created_at",
        }
        columns = {
            column["name"]: column
            for column in inspector.get_columns("inbox_items")
        }
        assert set(columns) == {
            "id",
            "item_type",
            "title",
            "raw_text",
            "source_url",
            "original_filename",
            "mime_type",
            "processing_status",
            "error_message",
            "storage_path",
            "extracted_text",
            "ai_description",
            "user_context",
            "owner_user_id",
            "created_at",
            "updated_at",
            "link_card",  # change 015 (migration 0024)
            "source_summary",  # change 022 (migration 0030)
        }
        assert columns["updated_at"]["nullable"] is True
        assert {
            column["name"]
            for column in inspector.get_columns("analysis_runs")
        } == {
            "id",
            "started_at",
            "completed_at",
            "status",
            "mode",
            "result_json",
            "owner_user_id",
        }
        assert {
            column["name"]
            for column in inspector.get_columns("item_insights")
        } == {
            "item_id",
            "analysis_run_id",
            "category",
            "concise_title",
            "priority",
            "topic_id",
            "tags_json",
            "rationale",
            "user_title",
            "user_topic_id",
            "user_priority",
            "user_tags_json",
            "needs_review",
            "updated_at",
            # change 014 (migration 0023)
            "filing_rule",
            "filing_confidence",
            "filing_choices",
            "filed_by",
            "filing_pending",
            "ai_summary",
            "suggested_action",
            "cleaned_transcript",
            # change 016 (migration 0027)
            "memory_used",
        }
        assert {
            column["name"]
            for column in inspector.get_columns("tasks")
        } == {
            "id",
            "text",
            "priority",
            "timing_text",
            "ai_timing_text",
            "timing_confirmed",
            "due_on",
            "due_time",
            "user_edited",
            "due_confidence",
            "snoozed_until",
            "reminder_at",
            "status",
            "dedup_key",
            "owner_user_id",
            "created_at",
            "updated_at",
            "user_priority",
            "completed_at",
            "date_recheck",
            "suggested_due_on",
            "suggested_due_time",
            # change 018 (migration 0028)
            "someday",
            "someday_since",
        }
        assert "calendar_action_receipts" in set(inspector.get_table_names())
        assert {
            column["name"] for column in inspector.get_columns("topics")
        } == {
            "id",
            "name",
            "description",
            "owner_user_id",
            "created_at",
            "updated_at",
            "archived",
            "parent_topic_id",
            "bot_key",
            "origin",
            # change 020 (migration 0029): a topic's history from a proposal
            "proposed_by",
            "evidence_item_ids",
            "approved_at",
        }
        assert {
            column["name"]
            for column in inspector.get_columns("task_source_items")
        } == {"task_id", "item_id"}
        assert {
            "password_hash",
            "password_changed_at",
            "status",
            "failed_password_attempts",
            "locked_until",
            "last_login_at",
            "email_verified_at",
            "adult_confirmed_at",
            "terms_accepted_at",
        } <= {column["name"] for column in inspector.get_columns("users")}
        assert {
            "id",
            "user_id",
            "token_hash",
            "auth_method",
            "created_at",
            "last_seen_at",
            "idle_expires_at",
            "absolute_expires_at",
            "revoked_at",
            "revoked_reason",
            "device_label",
        } == {column["name"] for column in inspector.get_columns("auth_sessions")}
        assert {
            "id",
            "purpose",
            "identifier_hash",
            "user_id",
            "code_hash",
            "attempts",
            "max_attempts",
            "created_at",
            "expires_at",
            "consumed_at",
        } == {column["name"] for column in inspector.get_columns("otp_challenges")}
        with engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            topic_count = connection.scalar(text("SELECT COUNT(*) FROM topics"))
        assert revision == "0031_merge_team_work"
        assert topic_count >= 9
    finally:
        engine.dispose()


def test_upgrade_adopts_legacy_database_without_changing_notes(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "legacy.db"
    existing_notes = [
        (4, "Existing note", "2026-01-01T10:00:00+00:00"),
        (9, "Another existing note", "2026-01-02T10:00:00+00:00"),
    ]

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO notes (id, text, created_at) VALUES (?, ?, ?)",
            existing_notes,
        )
        connection.commit()

    command.upgrade(alembic_config(database_path), "head")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        assert {"inbox_items", "notes"} <= set(
            inspect(engine).get_table_names()
        )
        with engine.connect() as connection:
            migrated_notes = connection.execute(
                text(
                    "SELECT id, text, created_at FROM notes ORDER BY id"
                )
            ).all()
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
            updated_values = connection.execute(
                text("SELECT updated_at FROM notes ORDER BY id")
            ).scalars().all()
            migrated_items = connection.execute(
                text(
                    """
                    SELECT
                        id,
                        item_type,
                        title,
                        raw_text,
                        source_url,
                        original_filename,
                        mime_type,
                        processing_status,
                        created_at,
                        updated_at
                    FROM inbox_items
                    ORDER BY id
                    """
                )
            ).all()
            next_id = connection.execute(
                text(
                    """
                    INSERT INTO inbox_items (
                        item_type,
                        raw_text,
                        processing_status,
                        created_at
                    )
                    VALUES ('text', 'New item', 'ready', '2026-01-03')
                    """
                )
            ).lastrowid
        assert [tuple(note) for note in migrated_notes] == existing_notes
        assert updated_values == [None, None]
        assert [tuple(item) for item in migrated_items] == [
            (
                note_id,
                "text",
                None,
                note_text,
                None,
                None,
                None,
                "ready",
                created_at,
                None,
            )
            for note_id, note_text, created_at in existing_notes
        ]
        assert next_id == 10
        assert revision == "0031_merge_team_work"
    finally:
        engine.dispose()


def test_upgrade_consolidates_tasks_that_share_a_source(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "duplicate_tasks.db"
    config = alembic_config(database_path)
    command.upgrade(config, "0005_create_tasks")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO inbox_items (
                    id, item_type, raw_text, processing_status, created_at
                )
                VALUES (1, 'text', 'Prepare notes', 'ready', '2026-01-01')
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO tasks (
                    id, text, priority, timing_text, status, dedup_key,
                    created_at, updated_at
                )
                VALUES
                    (
                        1, 'Prepare class notes', 'Low', NULL, 'completed',
                        'old-key', '2026-01-01', '2026-01-02'
                    ),
                    (
                        2, 'Prepare notes for class', 'High', NULL, 'open',
                        'new-key', '2026-01-03', '2026-01-04'
                    )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO task_source_items (task_id, item_id)
                VALUES (1, 1), (2, 1)
                """
            )
        )

    command.upgrade(config, "head")

    try:
        with engine.connect() as connection:
            tasks = connection.execute(
                text(
                    """
                    SELECT id, text, priority, status, created_at, updated_at
                    FROM tasks
                    """
                )
            ).all()
            links = connection.execute(
                text(
                    """
                    SELECT task_id, item_id
                    FROM task_source_items
                    """
                )
            ).all()
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )

        assert [tuple(task) for task in tasks] == [
            (
                1,
                "Prepare notes for class",
                "High",
                "completed",
                "2026-01-01",
                "2026-01-04",
            )
        ]
        assert [tuple(link) for link in links] == [(1, 1)]
        assert revision == "0031_merge_team_work"

        # Milestone 2 drops the one-task-per-source unique index so one
        # inbox item may source multiple durable tasks.
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO tasks (
                        id, text, priority, status, dedup_key,
                        created_at, updated_at, timing_confirmed
                    )
                    VALUES (
                        2, 'Another task', 'Medium', 'open',
                        'another-key', '2026-01-05', '2026-01-05', 0
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO task_source_items (task_id, item_id)
                    VALUES (2, 1)
                    """
                )
            )
            multi_links = connection.execute(
                text(
                    """
                    SELECT task_id, item_id
                    FROM task_source_items
                    ORDER BY task_id
                    """
                )
            ).all()
        assert [tuple(link) for link in multi_links] == [(1, 1), (2, 1)]
    finally:
        engine.dispose()


def test_upgrade_to_password_auth_scopes_topic_names_per_owner(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    database_path = tmp_path / "topics_per_owner.db"
    config = alembic_config(database_path)
    command.upgrade(config, "0011_multi_user_ownership")

    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with engine.begin() as connection:
            work_id = connection.scalar(
                text("SELECT id FROM topics WHERE name = 'Work'")
            )
            connection.execute(
                text(
                    """
                    INSERT INTO inbox_items (
                        id, item_type, raw_text, processing_status,
                        created_at, owner_user_id
                    )
                    VALUES (1, 'text', 'Quarterly review', 'ready',
                            '2026-01-01', 1)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO analysis_runs (
                        id, started_at, status, mode, owner_user_id
                    )
                    VALUES (1, '2026-01-01', 'succeeded', 'fallback', 1)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO item_insights (
                        item_id, analysis_run_id, category, concise_title,
                        priority, updated_at, topic_id
                    )
                    VALUES (1, 1, 'Work', 'Review', 'High', '2026-01-01',
                            :topic_id)
                    """
                ),
                {"topic_id": work_id},
            )

        command.upgrade(config, "head")

        with engine.begin() as connection:
            assert connection.scalar(
                text("SELECT topic_id FROM item_insights WHERE item_id = 1")
            ) == work_id
            # 0018 renamed v1's "Work" to "Work & career"; the note stayed on it.
            assert connection.scalar(
                text("SELECT name FROM topics WHERE id = :id"), {"id": work_id}
            ) == "Work & career"
            connection.execute(
                text(
                    """
                    INSERT INTO users (email, display_name, auth_provider,
                                       created_at)
                    VALUES ('second@example.com', 'Second', 'password',
                            '2026-01-02')
                    """
                )
            )
            second_id = connection.scalar(
                text("SELECT id FROM users WHERE email = 'second@example.com'")
            )
            # Same topic name for a different owner is now allowed.
            connection.execute(
                text(
                    """
                    INSERT INTO topics (name, owner_user_id, created_at,
                                        updated_at, archived)
                    VALUES ('Work & career', :owner, '2026-01-02', '2026-01-02', 0)
                    """
                ),
                {"owner": second_id},
            )
        with pytest.raises(Exception):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO topics (name, owner_user_id, created_at,
                                            updated_at, archived)
                        VALUES ('Work & career', 1, '2026-01-03', '2026-01-03', 0)
                        """
                    )
                )
    finally:
        engine.dispose()


def test_app_refuses_to_start_on_out_of_date_schema(tmp_path, monkeypatch):
    import importlib
    import sys

    database_path = tmp_path / "behind.db"
    config = alembic_config(database_path)
    command.upgrade(config, "0011_multi_user_ownership")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.delenv("LIFE_INBOX_AUTO_CREATE_TABLES", raising=False)
    modules = ("app.main", "app.database", "app.auth", "app.config")
    for name in modules:
        sys.modules.pop(name, None)
    try:
        with pytest.raises(RuntimeError, match="alembic upgrade head"):
            importlib.import_module("app.main")

        for name in modules:
            sys.modules.pop(name, None)
        command.upgrade(config, "head")
        main = importlib.import_module("app.main")
        assert main.app is not None
        sys.modules["app.database"].engine.dispose()
    finally:
        for name in modules:
            sys.modules.pop(name, None)
