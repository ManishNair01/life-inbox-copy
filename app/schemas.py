from typing import Optional

from pydantic import BaseModel, Field, field_validator


class NoteText(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def reject_whitespace_only_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Note text must contain non-whitespace characters")
        return value


class NoteCreate(NoteText):
    pass


class NoteUpdate(NoteText):
    pass


class Note(BaseModel):
    id: int
    text: str
    created_at: str


class InboxItemText(BaseModel):
    raw_text: str = Field(min_length=1, max_length=2000)

    @field_validator("raw_text")
    @classmethod
    def reject_whitespace_only_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Item text must contain non-whitespace characters")
        return value


class InboxItemCreate(InboxItemText):
    pass


class InboxItemUpdate(InboxItemText):
    pass


class InboxItem(BaseModel):
    id: int
    item_type: str
    title: Optional[str]
    raw_text: Optional[str]
    source_url: Optional[str]
    original_filename: Optional[str]
    mime_type: Optional[str]
    processing_status: str
    created_at: str
    updated_at: Optional[str]
