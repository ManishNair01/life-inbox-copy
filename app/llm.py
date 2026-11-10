"""One path for every AI call in Life Inbox.

Every LLM and speech-to-text request goes through this module, so that:

- the client, key and model come from one place (`.env`);
- every request has a timeout;
- prompt size is measured, and refused above a limit when the caller sets one;
- every request (never its text) is written to the AI call log;
- a provider "not found" on a text request gets exactly one quick retry
  (the OpenAI SDK already retries rate limits, timeouts and server errors);
- an unusable JSON answer can get one repair request, when the caller asks.

Callers keep their own fallbacks: when a call raises, they use the offline
path. Never create an `OpenAI` client anywhere else.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3.5-bolt-e4b"
DEFAULT_TEXT_TIMEOUT_SECONDS = 60.0
AUDIO_TIMEOUT_SECONDS = 180.0
CHARS_PER_TOKEN = 4  # rough rule of thumb for English text
RETRY_DELAY_SECONDS = 1.0


class LlmError(RuntimeError):
    """An AI call could not produce a usable answer."""


class InvalidOutput(LlmError):
    """The model answered, but the answer couldn't be used."""


class PromptTooLarge(LlmError):
    """The prompt was over the caller's limit, so nothing was sent."""


class AiSwitchedOff(LlmError):
    """The user switched AI processing off (change 025): nothing is sent."""


# Change 025 (decision Q): the user's AI switch. app/database.py registers the
# check; with none registered (scripts, unit tests), AI is allowed.
_switch: Optional[Callable[[], bool]] = None


def set_switch(check: Optional[Callable[[], bool]]) -> None:
    global _switch
    _switch = check


def allowed() -> bool:
    """The signed-in user's AI switch. Fails closed: if it can't be read,
    nothing is sent."""
    if _switch is None:
        return True
    try:
        return bool(_switch())
    except Exception:
        logger.warning("Couldn't read the AI switch; treating AI as off")
        return False


# --- configuration ------------------------------------------------------------


def api_key() -> str:
    nvidia = os.getenv("NVIDIA_API_KEY", "").strip()
    if nvidia:
        # NVIDIA keys start with "nvapi-"; restore it if it was pasted without.
        return nvidia if nvidia.startswith(("nvapi-", "Bearer ")) else f"nvapi-{nvidia}"
    return os.getenv("OPENAI_API_KEY", "").strip()


def is_configured() -> bool:
    """A key is set and the user's AI switch is on (change 025)."""
    return bool(api_key()) and allowed()


def provider() -> str:
    return "nvidia_nim" if os.getenv("NVIDIA_API_KEY", "").strip() else "openai"


def text_model() -> str:
    return os.getenv("NVIDIA_LLM_MODEL") or os.getenv("OPENAI_MODEL") or DEFAULT_MODEL


def base_url() -> str:
    return os.getenv("NVIDIA_BASE_URL", DEFAULT_BASE_URL)


def text_timeout_seconds() -> float:
    try:
        value = float(os.getenv("LIFE_INBOX_AI_TIMEOUT_SECONDS", ""))
    except ValueError:
        return DEFAULT_TEXT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TEXT_TIMEOUT_SECONDS


def _tokens(chars: int) -> int:
    return -(-chars // CHARS_PER_TOKEN)


def estimate_tokens(text: str) -> int:
    return _tokens(len(text))


def make_client(*, key: Optional[str] = None, timeout: Optional[float] = None):
    """An OpenAI-compatible client for the configured provider.

    Simpler stand-ins (older SDKs, test fakes) may not accept every keyword,
    so fewer are tried in turn, ending with no arguments at all.
    """
    from openai import OpenAI

    chosen_key = api_key() if key is None else key
    attempts = (
        {"base_url": base_url(), "api_key": chosen_key, "timeout": timeout or text_timeout_seconds()},
        {"base_url": base_url(), "api_key": chosen_key},
        {"api_key": chosen_key},
        {},
    )
    for kwargs in attempts[:-1]:
        try:
            return OpenAI(**kwargs)
        except TypeError:
            continue
    return OpenAI(**attempts[-1])


def extract_json_object(raw: str) -> dict:
    """The JSON object in a model's answer, tolerating ``` fences around it."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.replace("```json", "").replace("```", "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return json.loads(raw[start:end + 1])


# --- the call log ----------------------------------------------------------------


def _record(
    action: str,
    model: str,
    outcome: str,
    attempt: int,
    input_size: int,
    output_size: int = 0,
    *,
    started: Optional[float] = None,
    status_code: Optional[int] = None,
) -> None:
    """Log one request for the signed-in user: sizes and outcome, never text.

    Calls made outside a signed-in request (scripts, unit tests) aren't logged,
    and logging problems never break the feature that made the call.
    """
    database = sys.modules.get("app.database")
    if database is None:
        return
    try:
        owner = database.get_current_owner_id()
        if owner is None:
            return
        duration_ms = int((time.monotonic() - started) * 1000) if started else 0
        database.record_ai_call(
            owner_user_id=owner,
            action=action,
            model=model,
            outcome=outcome,
            attempt=attempt,
            status_code=status_code if isinstance(status_code, int) else None,
            input_size=input_size,
            output_size=output_size,
            duration_ms=duration_ms,
        )
    except Exception:
        logger.debug("Could not record an AI call", exc_info=True)


# --- text -------------------------------------------------------------------------


def _send_text(client: Any, model: str, messages: list[dict], temperature: float) -> Optional[str]:
    """One request. None means the client offers no way to send it."""
    if hasattr(client, "chat") and hasattr(client.chat, "completions"):
        response = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature
        )
        choices = getattr(response, "choices", None) or []
        message = getattr(choices[0], "message", None) if choices else None
        return (getattr(message, "content", None) or "") if message is not None else ""
    if hasattr(client, "responses"):
        # Older OpenAI-compatible clients (and simple test fakes) take one string.
        text = "\n\n".join(message.get("content") or "" for message in messages)
        response = client.responses.create(model=model, prompt=text, temperature=temperature)
        return getattr(response, "output_text", "") or ""
    return None


def complete_text(
    action: str,
    prompt: Optional[str] = None,
    *,
    messages: Optional[list[dict]] = None,
    temperature: float = 0.2,
    model: Optional[str] = None,
    key: Optional[str] = None,
    max_prompt_tokens: Optional[int] = None,
    usable: Optional[Callable[[str], bool]] = None,
    attempt: int = 1,
) -> str:
    """Send one text prompt (or chat messages) and return the model's text.

    `usable` lets the caller mark an answer as unusable in the log. Raises on
    provider errors after the one "not found" retry; callers fall back.
    """
    if not allowed():
        raise AiSwitchedOff("AI processing is switched off for this account.")
    if messages is None:
        messages = [{"role": "user", "content": prompt or ""}]
    chosen_model = model or text_model()
    size = sum(len(message.get("content") or "") for message in messages)
    if max_prompt_tokens is not None and _tokens(size) > max_prompt_tokens:
        _record(action, chosen_model, "too_large", attempt, size)
        raise PromptTooLarge(
            f"The {action} prompt is about {_tokens(size)} tokens; "
            f"the limit is {max_prompt_tokens}."
        )

    client = make_client(key=key, timeout=text_timeout_seconds())
    number = attempt
    while True:
        started = time.monotonic()
        try:
            text = _send_text(client, chosen_model, messages, temperature)
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            _record(action, chosen_model, "error", number, size, started=started, status_code=status)
            if status == 404 and number == attempt:
                # Seen once from NVIDIA for a model that worked moments before
                # and after; a second try is cheap. A real wrong model fails again.
                logger.warning("AI provider said 'not found' for %s; retrying once", action)
                time.sleep(RETRY_DELAY_SECONDS)
                number += 1
                continue
            raise
        if text is None:
            return ""
        ok = usable is None or usable(text)
        _record(action, chosen_model, "ok" if ok else "invalid", number, size, len(text), started=started)
        return text


def complete_json(
    action: str,
    prompt: str,
    *,
    validate: Optional[Callable[[dict], Optional[str]]] = None,
    repair: bool = False,
    temperature: float = 0.2,
    model: Optional[str] = None,
    key: Optional[str] = None,
    max_prompt_tokens: Optional[int] = None,
) -> dict:
    """Send a prompt that asks for JSON, and return the parsed object.

    `validate` returns None when the object is usable, or a short reason when
    it isn't. With `repair=True`, an unusable answer gets one more request
    that names the reason. Raises InvalidOutput if it still can't be used.
    """
    state: dict = {}

    def usable(text: str) -> bool:
        state.clear()
        try:
            data = extract_json_object(text)
        except (ValueError, TypeError):
            state["problem"] = "The answer was not a single valid JSON object."
            return False
        try:
            problem = validate(data) if validate else None
        except Exception:
            problem = "The answer did not match the required shape."
        if problem:
            state["problem"] = problem
            return False
        state["data"] = data
        return True

    options = dict(temperature=temperature, model=model, key=key, max_prompt_tokens=max_prompt_tokens)
    complete_text(action, prompt, usable=usable, **options)
    if "data" in state:
        return state["data"]
    if repair and state.get("problem"):
        follow_up = (
            f"{prompt}\n\nYour previous answer could not be used: {state['problem']}\n"
            "Reply again with ONLY the corrected JSON, in exactly the shape described above."
        )
        complete_text(action, follow_up, usable=usable, attempt=2, **options)
        if "data" in state:
            return state["data"]
    raise InvalidOutput(state.get("problem") or "The answer could not be used.")


# --- speech -----------------------------------------------------------------------


def transcribe(action: str, *, file: tuple, model: str, key: Optional[str] = None) -> str:
    """Speech to text. Returns "" when the client can't transcribe; raises on errors."""
    client = make_client(key=key, timeout=AUDIO_TIMEOUT_SECONDS)
    if not (hasattr(client, "audio") and hasattr(client.audio, "transcriptions")):
        return ""
    size = len(file[1]) if len(file) > 1 and file[1] is not None else 0
    started = time.monotonic()
    try:
        result = client.audio.transcriptions.create(model=model, file=file)
    except Exception as exc:
        _record(action, model, "error", 1, size, started=started,
                status_code=getattr(exc, "status_code", None))
        raise
    text = result.strip() if isinstance(result, str) else str(getattr(result, "text", "") or "").strip()
    _record(action, model, "ok", 1, size, len(text), started=started)
    return text
