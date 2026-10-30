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
