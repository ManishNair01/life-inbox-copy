import base64
from types import SimpleNamespace

from app import gemini


def _capture(monkeypatch, payload):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json})
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)

    monkeypatch.setattr(gemini.requests, "post", fake_post)
    return calls


def test_api_key_prefers_gemini_then_google(monkeypatch):
    assert gemini.api_key() is None
    monkeypatch.setenv("GOOGLE_API_KEY", "g")
    assert gemini.api_key() == "g"
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    assert gemini.api_key() == "m"


def test_generate_text_joins_parts_skips_thoughts_and_sends_key_header(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    calls = _capture(
        monkeypatch,
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "plan", "thought": True},
                            {"text": "{"},
                            {"text": "}"},
                        ]
                    }
                }
            ]
        },
    )

    assert gemini.generate_text("hi") == "{}"
    assert calls[0]["headers"] == {"x-goog-api-key": "secret"}
    assert calls[0]["url"].endswith(f"models/{gemini.generation_model()}:generateContent")
    assert "secret" not in calls[0]["url"]


def test_transcribe_audio_sends_inline_audio(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    calls = _capture(
        monkeypatch,
        {"candidates": [{"content": {"parts": [{"text": "  hello there  "}]}}]},
    )

    assert gemini.transcribe_audio(b"abc", "audio/wav") == "hello there"
    inline = calls[0]["json"]["contents"][0]["parts"][1]["inline_data"]
    assert inline == {
        "mime_type": "audio/wav",
        "data": base64.b64encode(b"abc").decode("ascii"),
    }


def test_post_retries_transient_errors_then_succeeds(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    attempts = []

    def fake_post(url, headers, json, timeout):
        attempts.append(1)
        if len(attempts) == 1:
            raise gemini.requests.ReadTimeout()
        if len(attempts) == 2:
            error = gemini.requests.HTTPError(response=SimpleNamespace(status_code=503))
            return SimpleNamespace(
                raise_for_status=lambda: (_ for _ in ()).throw(error)
            )
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    monkeypatch.setattr(gemini.requests, "post", fake_post)

    assert gemini.generate_text("hi") == "ok"
    assert len(attempts) == 3


def test_post_does_not_retry_quota_or_client_errors(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)

    for status in (404, 429):
        attempts = []
        error = gemini.requests.HTTPError(response=SimpleNamespace(status_code=status))

        def fake_post(url, headers, json, timeout, _error=error, _attempts=attempts):
            _attempts.append(1)
            return SimpleNamespace(
                raise_for_status=lambda: (_ for _ in ()).throw(_error)
            )

        monkeypatch.setattr(gemini.requests, "post", fake_post)
        try:
            gemini.generate_text("hi")
        except gemini.requests.HTTPError:
            pass
        assert len(attempts) == 1
