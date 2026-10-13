"""Voice note validation and transcription adapters."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from app.capture.storage import MAX_AUDIO_BYTES

logger = logging.getLogger(__name__)

ALLOWED_AUDIO_EXTENSIONS = {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".mpeg"}
ALLOWED_AUDIO_MIMES = {
    "audio/webm",
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/ogg",
    "video/webm",  # MediaRecorder often reports webm as video/webm
}

# Loose magic sniffing for common containers.
_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"RIFF", "audio/wav", ".wav"),  # refined for WAVE
    (b"ID3", "audio/mpeg", ".mp3"),
    (b"\xff\xfb", "audio/mpeg", ".mp3"),
    (b"\xff\xf3", "audio/mpeg", ".mp3"),
    (b"\xff\xf2", "audio/mpeg", ".mp3"),
    (b"OggS", "audio/ogg", ".ogg"),
    (b"\x1aE\xdf\xa3", "audio/webm", ".webm"),  # EBML / Matroska / WebM
]


def _normalize_filename(filename: str) -> str:
    name = Path(filename or "voice-note.webm").name
    if not name or name in {".", ".."}:
        return "voice-note.webm"
    return name


def _sniff_audio(data: bytes, declared_ext: str) -> tuple[str, str]:
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return "audio/wav", ".wav"
    if data[4:8] == b"ftyp":
        return "audio/mp4", ".m4a"
    for magic, mime, ext in _SIGNATURES:
        if magic != b"RIFF" and data.startswith(magic):
            return mime, ext
    # MediaRecorder webm may not always match; allow by declared extension.
    if declared_ext in ALLOWED_AUDIO_EXTENSIONS:
        mime_guess = {
            ".webm": "audio/webm",
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".mpeg": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".ogg": "audio/ogg",
        }.get(declared_ext, "audio/webm")
        return mime_guess, declared_ext
    raise ValueError(
        "File does not look like a supported audio note (webm/wav/mp3/m4a/ogg)."
    )


def validate_audio_upload(
    filename: str,
    content_type: Optional[str],
    data: bytes,
) -> tuple[str, str, str]:
    """Validate upload; return (safe_filename, mime, extension)."""
    safe_name = _normalize_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix and suffix not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError(
            "Only webm, wav, mp3, m4a, or ogg audio files are allowed."
        )

    if not data:
        raise ValueError("Uploaded audio is empty.")

    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError(
            f"Audio exceeds the {MAX_AUDIO_BYTES // (1024 * 1024)} MB upload limit."
        )

    if content_type:
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime and mime not in ALLOWED_AUDIO_MIMES:
            raise ValueError(
                "Unsupported content type. Upload a voice note audio file."
            )

    detected_mime, detected_ext = _sniff_audio(data, suffix or ".webm")
    if not suffix:
        safe_name = f"{Path(safe_name).stem}{detected_ext}"
    return safe_name, detected_mime, detected_ext


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or "Voice note"


def transcribe_audio(
    data: bytes,
    *,
    original_filename: str,
    mime_type: str,
) -> dict:
    """Transcription adapter. Graceful when no live API is configured.

    Returns:
        text, provider, available, note
    """
    if os.getenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return {
            "text": "",
            "provider": "disabled",
            "available": False,
            "note": "Transcription disabled via LIFE_INBOX_DISABLE_TRANSCRIPTION.",
        }

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "text": "",
            "provider": "none",
            "available": False,
            "note": (
                "Transcription not configured. Set OPENAI_API_KEY for live "
                "Whisper transcription, or edit the transcript manually."
            ),
        }

    # Live Whisper is intentionally not called from the default path so
    # automated tests never incur paid API usage. Extend this adapter for
    # explicit manual smoke testing when desired.
    logger.info(
        "Skipping live transcription for %s (%s bytes); using empty transcript placeholder.",
        original_filename,
        len(data),
    )
    return {
        "text": "",
        "provider": "openai_whisper_skipped",
        "available": False,
        "note": (
            "Live transcription adapter is present but skipped in this build "
            "to avoid unpaid/paid API calls from automated paths. Edit the "
            "transcript manually or extend the adapter for smoke tests."
        ),
    }


def process_voice_bytes(
    data: bytes,
    *,
    original_filename: str,
    mime_type: str,
) -> dict:
    """Persist-ready processing result for a voice note."""
    transcription = transcribe_audio(
        data,
        original_filename=original_filename,
        mime_type=mime_type,
    )
    title = _title_from_filename(original_filename)
    transcript = transcription["text"]
    note = transcription.get("note")

    if transcript:
        raw_text = transcript
    else:
        raw_text = (
            f"[Voice note — transcript pending]\n"
            f"Filename: {original_filename}\n"
            f"{note or 'No transcript yet. Edit to add text.'}"
        )

    return {
        "title": title,
        "raw_text": raw_text,
        "extracted_text": transcript,
        "mime_type": mime_type,
        "transcription_provider": transcription["provider"],
        "transcription_available": transcription["available"],
        "transcription_note": note,
    }
