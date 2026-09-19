from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class Note(BaseModel):
    id: int
    text: str
    created_at: str
