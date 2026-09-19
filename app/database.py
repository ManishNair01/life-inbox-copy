import os
from datetime import datetime, timezone
from pathlib import Path

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


def init_db():
    """Create missing tables without running or applying Alembic migrations."""
    Base.metadata.create_all(bind=engine)


def add_note_to_db(text: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with SessionLocal() as session:
        note = NoteRecord(text=text, created_at=now)
        session.add(note)
        session.commit()
        return {"id": note.id, "text": note.text, "created_at": note.created_at}


def list_notes_from_db() -> list[dict]:
    with SessionLocal() as session:
        notes = session.scalars(
            select(NoteRecord).order_by(NoteRecord.id.asc())
        ).all()
        return [
            {"id": note.id, "text": note.text, "created_at": note.created_at}
            for note in notes
        ]
