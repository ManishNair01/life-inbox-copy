import sqlite3
from pathlib import Path

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
        assert {"alembic_version", "inbox_items", "notes"} <= set(
            inspector.get_table_names()
        )
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
            "created_at",
            "updated_at",
        }
        assert columns["updated_at"]["nullable"] is True
        with engine.connect() as connection:
            revision = connection.scalar(
                text("SELECT version_num FROM alembic_version")
            )
        assert revision == "0003_create_inbox_items"
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
        assert revision == "0003_create_inbox_items"
    finally:
        engine.dispose()
