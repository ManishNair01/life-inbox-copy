import logging
from types import SimpleNamespace

import pytest

from app import gemini
from app.capture import voice_extract


def _respond(monkeypatch, payload):
    monkeypatch.setattr(
        gemini.requests,
        "post",
        lambda url, headers, json, timeout: SimpleNamespace(
            raise_for_status=lambda: None, json=lambda: payload
        ),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": []},
        {"candidates": [{"finishReason": "SAFETY"}]},
    ],
)
def test_blocked_or_empty_responses_raise_instead_of_returning_garbage(
    monkeypatch, payload
):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    _respond(monkeypatch, payload)
    with pytest.raises((KeyError, IndexError)):
        gemini.generate_text("hi")


def _transcribe(monkeypatch, behaviour):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-key-123")
    monkeypatch.setattr(gemini, "transcribe_audio", behaviour)
    return voice_extract.transcribe_audio(
        b"abc", original_filename="memo.wav", mime_type="audio/wav"
    )


def test_voice_transcription_falls_back_when_gemini_blocks_response(monkeypatch):
    def blocked(data, mime):
        raise KeyError("candidates")

    result = _transcribe(monkeypatch, blocked)
    assert result["available"] is False
    assert result["provider"] == "unavailable"
    assert result["text"] == ""
    assert "KeyError" not in (result["note"] or "")


def test_voice_transcription_with_no_speech_is_available_but_noted(monkeypatch):
    result = _transcribe(monkeypatch, lambda data, mime: "  ")
    assert result["available"] is True
    assert result["text"] == ""
    assert result["note"]


def test_api_key_is_not_logged_on_http_failure(monkeypatch, caplog):
    secret = "secret-key-123"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)

    def fake_post(url, headers, json, timeout):
        error = gemini.requests.HTTPError(
            "503 Server Error for url: " + url,
            response=SimpleNamespace(status_code=503),
        )
        return SimpleNamespace(raise_for_status=lambda: (_ for _ in ()).throw(error))

    monkeypatch.setattr(gemini.requests, "post", fake_post)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(gemini.requests.HTTPError) as raised:
            gemini.generate_text("hi")
        voice_result = None
        monkeypatch.setattr(
            gemini, "transcribe_audio", lambda d, m: gemini.generate_text("x")
        )
        voice_result = voice_extract.transcribe_audio(
            b"abc", original_filename="memo.wav", mime_type="audio/wav"
        )

    assert secret not in str(raised.value)
    assert secret not in caplog.text
    assert secret not in str(voice_result)


def test_concurrent_gemini_calls_are_capped(monkeypatch):
    import threading
    import time

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setattr(gemini, "_slots", threading.BoundedSemaphore(2))
    state = {"now": 0, "peak": 0}
    guard = threading.Lock()

    def slow_post(url, headers, json, timeout):
        with guard:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.05)
        with guard:
            state["now"] -= 1
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    monkeypatch.setattr(gemini.requests, "post", slow_post)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(gemini.generate_text("hi")))
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == ["ok"] * 8
    assert state["peak"] <= 2


def test_busy_gemini_raises_and_callers_fall_back(monkeypatch):
    import threading

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    exhausted = threading.BoundedSemaphore(1)
    exhausted.acquire()
    monkeypatch.setattr(gemini, "_slots", exhausted)
    monkeypatch.setattr(gemini, "SLOT_WAIT_SECONDS", 0.01)

    with pytest.raises(gemini.GeminiBusy):
        gemini.generate_text("hi")

    from app.organizer import analyze_inbox_with_gemini

    result = analyze_inbox_with_gemini([{"id": 1, "text": "Call the dentist"}])
    assert result["mode"] == "fallback_after_api_error"

    voice = voice_extract.transcribe_audio(
        b"abc", original_filename="m.wav", mime_type="audio/wav"
    )
    assert voice["available"] is False


def test_gemini_slot_is_released_after_errors(monkeypatch):
    import threading

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(gemini, "_slots", slots)
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)

    def failing_post(url, headers, json, timeout):
        raise gemini.requests.ConnectionError()

    monkeypatch.setattr(gemini.requests, "post", failing_post)
    with pytest.raises(gemini.requests.ConnectionError):
        gemini.generate_text("hi")

    assert slots.acquire(blocking=False)
