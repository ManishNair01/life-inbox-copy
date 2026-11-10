"""Voice note validation and transcription adapters."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from app import llm
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

import shutil
import subprocess

STRICT_CLEANUP_SYSTEM_PROMPT = """You are an expert audio transcript cleaner for a personal Life Inbox.
Your task is to clean up a raw spoken transcript into clear, written notes.

Rules:
1. Remove stutters, filler words (e.g., "um", "uh", "like", "you know", "er", "ah"), false starts, and accidental immediate repetitions.
2. Fix punctuation, capitalization, and minor grammatical slips.
3. STRICT PRESERVATION: You MUST preserve the speaker's exact meaning, facts, person names, places, numbers, amounts, dates, and intent.
4. DO NOT add any information, external facts, or commentary.
5. DO NOT summarize away details or shorten the content.
6. DO NOT answer questions asked in the speech; output the spoken thoughts as notes.
7. Output ONLY the cleaned transcript text. No preamble, no quotes, no markdown fences."""


def convert_audio_to_wav(data: bytes, filename: str) -> tuple[bytes, str, str]:
    """Convert audio bytes to 16kHz mono WAV using ffmpeg if installed.
    Returns (audio_bytes, safe_filename, mime_type).
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return data, filename, "application/octet-stream"
    try:
        proc = subprocess.run(
            [
                ffmpeg_bin,
                "-y",
                "-i",
                "pipe:0",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-f",
                "wav",
                "pipe:1",
            ],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=15,
        )
        wav_bytes = proc.stdout
        wav_filename = f"{Path(filename).stem}.wav"
        return wav_bytes, wav_filename, "audio/wav"
    except Exception as e:
        logger.warning(
            "ffmpeg conversion to 16kHz mono wav failed: %s; using original audio",
            e,
        )
        return data, filename, "application/octet-stream"


def cleanup_transcript_with_llm(
    raw_transcript: str,
    *,
    api_key: str,
    model: str,
) -> str:
    """Clean raw speech transcript using the configured LLM (app/llm.py).
    Strictly preserves meaning, facts, and dates while stripping filler words and stutters.
    """
    if not raw_transcript or not raw_transcript.strip():
        return ""
    if not api_key:
        return raw_transcript
    from app.sensitive import looks_secret

    if looks_secret(raw_transcript):
        return raw_transcript  # a secret is never sent to the AI (change 016)

    try:
        cleaned = llm.complete_text(
            "voice_cleanup",
            messages=[
                {"role": "system", "content": STRICT_CLEANUP_SYSTEM_PROMPT},
                {"role": "user", "content": raw_transcript},
            ],
            temperature=0.1,
            model=model,
            key=api_key,
        )
        cleaned = (cleaned or "").strip()
        return cleaned if cleaned else raw_transcript
    except Exception as e:
        logger.warning(
            "NIM LLM transcript cleanup failed (%s); retaining raw transcript",
            e,
        )
        return raw_transcript


def _transcription_model() -> str:
    """Model for audio transcription; prefer NVIDIA_ASR_MODEL with whisper-large-v3 default."""
    nim_model = os.getenv("NVIDIA_ASR_MODEL", "").strip()
    if nim_model:
        return nim_model
    openai_model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "").strip()
    if openai_model:
        return openai_model
    return "openai/whisper-large-v3" if os.getenv("NVIDIA_API_KEY") else "whisper-1"


def _friendly_transcription_unavailable_note() -> str:
    return (
        "Transcription is temporarily unavailable. You can edit the "
        "transcript manually, or retry processing later."
    )


def transcribe_audio(
    data: bytes,
    *,
    original_filename: str,
    mime_type: str,
    candidate_transcript: Optional[str] = None,
) -> dict:
    """Transcription adapter. Graceful when no live API is configured.

    Returns:
        text, cleaned_text, provider, available, note
    """
    if os.getenv("LIFE_INBOX_DISABLE_TRANSCRIPTION", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return {
            "text": "",
            "cleaned_text": "",
            "provider": "disabled",
            "available": False,
            "note": "Transcription disabled via LIFE_INBOX_DISABLE_TRANSCRIPTION.",
        }

    # The "nvapi-" prefix is restored for NVIDIA keys only (app/llm.py);
    # an OpenAI key is used exactly as given.
    api_key = llm.api_key()

    if not api_key:
        key_name = "NVIDIA_API_KEY"
        return {
            "text": candidate_transcript or "",
            "cleaned_text": candidate_transcript or "",
            "provider": "none",
            "available": bool(candidate_transcript),
            "note": (
                None
                if candidate_transcript
                else (
                    f"Transcription not configured. Set {key_name} for live "
                    "transcription, or edit the transcript manually."
                )
            ),
        }

    raw_text = ""
    try:
        model = _transcription_model()
        audio_payload, send_name, send_mime = convert_audio_to_wav(
            data, original_filename
        )
        safe_name = _normalize_filename(send_name)
        raw_text = llm.transcribe(
            "voice_transcribe",
            file=(
                safe_name,
                audio_payload,
                send_mime or mime_type or "application/octet-stream",
            ),
            model=model,
            key=api_key,
        )
    except Exception as e:
        logger.warning("Remote ASR transcription notice for %s: %s", original_filename, e)

    if not raw_text and candidate_transcript:
        raw_text = candidate_transcript.strip()

    if not raw_text:
        return {
            "text": "",
            "cleaned_text": "",
            "provider": "unavailable",
            "available": False,
            "note": _friendly_transcription_unavailable_note(),
        }

    # Change 014: no separate clean-up call. The filing call returns a tidied
    # transcript (saved as AI output); the raw one stays as the note's text.
    return {
        "text": raw_text,
        "cleaned_text": raw_text,
        "provider": llm.provider(),
        "available": True,
        "note": None,
    }


def process_voice_bytes(
    data: bytes,
    *,
    original_filename: str,
    mime_type: str,
    candidate_transcript: Optional[str] = None,
) -> dict:
    """Persist-ready processing result for a voice note."""
    transcription = transcribe_audio(
        data,
        original_filename=original_filename,
        mime_type=mime_type,
        candidate_transcript=candidate_transcript,
    )
    title = _title_from_filename(original_filename)
    raw_transcript = transcription["text"]
    cleaned_transcript = transcription.get("cleaned_text") or raw_transcript
    note = transcription.get("note")

    if cleaned_transcript:
        raw_text = cleaned_transcript
    else:
        raw_text = (
            f"[Voice note — transcript pending]\n"
            f"Filename: {original_filename}\n"
            f"{note or 'No transcript yet. Edit to add text.'}"
        )

    return {
        "title": title,
        "raw_text": raw_text,
        "extracted_text": raw_transcript,
        "mime_type": mime_type,
        "transcription_provider": transcription["provider"],
        "transcription_available": transcription["available"],
        "transcription_note": note,
    }
