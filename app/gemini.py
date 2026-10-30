"""Minimal Gemini REST client: text generation and audio transcription."""

from __future__ import annotations

import base64
import logging
import os
import threading
import time

import requests

logger = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT_SECONDS = 60
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5
# 429 is deliberately absent: quota exhaustion will not clear in seconds.
RETRYABLE_STATUSES = {500, 502, 503, 504}

# Requests run on the server's threadpool, so unlimited concurrent Gemini calls
# (each up to TIMEOUT_SECONDS) could occupy every worker thread. Callers that
# cannot get a slot in time get GeminiBusy and use their normal fallback.
DEFAULT_MAX_CONCURRENT = 4
SLOT_WAIT_SECONDS = 20


class GeminiBusy(Exception):
    """Too many Gemini calls are already in flight."""


class GeminiQuotaExceeded(Exception):
    """The current user used up today's Gemini call allowance."""


# Per user per UTC day; 0 disables the quota. Counts calls we make (a call that
# later fails still counts; internal retries of one call do not).
DEFAULT_DAILY_CALL_LIMIT = 100


def daily_call_limit() -> int:
    raw = os.getenv("GEMINI_DAILY_CALL_LIMIT", "").strip()
    if not raw:
        return DEFAULT_DAILY_CALL_LIMIT
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_DAILY_CALL_LIMIT


def _charge_quota() -> None:
    limit = daily_call_limit()
    if limit <= 0:
        return
    # Imported here: app.database imports modules that import this one.
    from app import database

    try:
        allowed = database.try_consume_ai_call(limit)
    except Exception:
        # Quota is cost control, not security: if the usage table is
        # unavailable, keep the feature working rather than fail every call.
        logger.warning("Gemini quota check failed; allowing the call", exc_info=True)
        return
    if not allowed:
        raise GeminiQuotaExceeded(
            f"Daily AI limit of {limit} calls reached; it resets at 00:00 UTC."
        )


def _max_concurrent() -> int:
    try:
        return max(1, int(os.getenv("GEMINI_MAX_CONCURRENT", "")))
    except ValueError:
        return DEFAULT_MAX_CONCURRENT


_slots = threading.BoundedSemaphore(_max_concurrent())

TRANSCRIBE_PROMPT = (
    "Transcribe the speech in this audio verbatim. Return only the transcript "
    "text, with no commentary. If there is no speech, return an empty string."
)


def api_key() -> str | None:
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or None


def generation_model() -> str:
    return os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


def transcription_model() -> str:
    return os.getenv("GEMINI_TRANSCRIPTION_MODEL", "").strip() or generation_model()


def _post(model: str, body: dict) -> dict:
    """POST to Gemini, retrying transient overload/timeout errors."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if not _slots.acquire(timeout=SLOT_WAIT_SECONDS):
                raise GeminiBusy(
                    "Too many concurrent Gemini requests; try again shortly."
                )
            try:
                response = requests.post(
                    f"{API_BASE}/models/{model}:generateContent",
                    headers={"x-goog-api-key": api_key() or ""},
                    json=body,
                    timeout=TIMEOUT_SECONDS,
                )
                response.raise_for_status()
                return response.json()
            finally:
                _slots.release()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == MAX_ATTEMPTS:
                raise
            logger.warning("Gemini request failed (attempt %d); retrying", attempt)
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status not in RETRYABLE_STATUSES or attempt == MAX_ATTEMPTS:
                raise
            logger.warning("Gemini returned %s (attempt %d); retrying", status, attempt)
        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise AssertionError("unreachable")


def _text_of(data: dict) -> str:
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(part.get("text", "") for part in parts if not part.get("thought"))


def generate_text(prompt: str) -> str:
    _charge_quota()
    data = _post(
        generation_model(),
        {"contents": [{"parts": [{"text": prompt}]}]},
    )
    return _text_of(data)


def transcribe_audio(data: bytes, mime_type: str) -> str:
    _charge_quota()
    encoded = base64.b64encode(data).decode("ascii")
    response = _post(
        transcription_model(),
        {
            "contents": [
                {
                    "parts": [
                        {"text": TRANSCRIBE_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime_type or "audio/webm",
                                "data": encoded,
                            }
                        },
                    ]
                }
            ]
        },
    )
    return _text_of(response).strip()
