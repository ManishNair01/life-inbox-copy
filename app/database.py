import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "life_inbox.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        conn.commit()


def add_note_to_db(text: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO notes (text, created_at) VALUES (?, ?)",
            (text, now),
        )
        conn.commit()
        note_id = cur.lastrowid
    return {"id": note_id, "text": text, "created_at": now}


def list_notes_from_db() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, text, created_at FROM notes ORDER BY id ASC"
        ).fetchall()
    return [dict(row) for row in rows]
