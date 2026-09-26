import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import Column, Integer, Text, create_engine, select
from sqlalchemy.orm import declarative_base, sessionmaker


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "life_inbox.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_DB_PATH}"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(DATABASE_URL, connect_args=_connect_args(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
Base = declarative_base()


class NoteRecord(Base):
    __tablename__ = "notes"
    __table_args__ = {"sqlite_autoincrement": True}

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    created_at = Column(Text, nullable=False)
    updated_at = Column(Text, nullable=True)


def init_db():
    """Create missing tables without running or applying Alembic migrations."""
    Base.metadata.create_all(bind=engine)


def _note_to_dict(note: NoteRecord) -> dict:
    return {"id": note.id, "text": note.text, "created_at": note.created_at}


def add_note_to_db(text: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        note = NoteRecord(text=text, created_at=now)
        session.add(note)
        session.commit()
        return _note_to_dict(note)


def list_notes_from_db() -> list[dict]:
    with SessionLocal() as session:
        notes = session.scalars(
            select(NoteRecord).order_by(NoteRecord.id.asc())
        ).all()
        return [_note_to_dict(note) for note in notes]


def update_note_in_db(note_id: int, text: str) -> Optional[dict]:
    with SessionLocal() as session:
        note = session.get(NoteRecord, note_id)
        if note is None:
            return None

        note.text = text
        note.updated_at = datetime.now(timezone.utc).isoformat()
        session.commit()
        return _note_to_dict(note)


def delete_note_from_db(note_id: int) -> bool:
    with SessionLocal() as session:
        note = session.get(NoteRecord, note_id)
        if note is None:
            return False

        session.delete(note)
        session.commit()
        return True
