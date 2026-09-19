from pathlib import Path
from typing import List

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.database import add_note_to_db, init_db, list_notes_from_db
from app.organizer import analyze_inbox_with_openai
from app.schemas import Note, NoteCreate


APP_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Life Inbox")
app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")

init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/notes", response_model=Note)
def create_note(payload: NoteCreate):
    return add_note_to_db(payload.text)


@app.get("/api/notes", response_model=List[Note])
def get_notes():
    return list_notes_from_db()


@app.post("/api/analyze")
def analyze_inbox():
    return analyze_inbox_with_openai(list_notes_from_db())


@app.get("/", response_class=HTMLResponse)
def index():
    return (APP_DIR / "templates" / "index.html").read_text(encoding="utf-8")
