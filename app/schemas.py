from pydantic import BaseModel, Field, field_validator


class NoteCreate(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def reject_whitespace_only_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Note text must contain non-whitespace characters")
        return value


class Note(BaseModel):
    id: int
    text: str
    created_at: str
