"""Circuit breaker: pause Gemini calls after repeated 429 responses."""

import logging
import time
from types import SimpleNamespace

import pytest

from app import gemini
from app.capture import voice_extract
from tests.test_api import client  # noqa: F401  (fixture: isolated temp DB)

OK_BODY = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}


def _script(monkeypatch, outcomes):
    """Fake requests.post: each outcome is an HTTP status or 'ok'. Returns the call log."""
    calls = []
    queue = list(outcomes)

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        outcome = queue.pop(0) if queue else "ok"
        if outcome == "ok":
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: OK_BODY)
        status, headers_ = outcome if isinstance(outcome, tuple) else (outcome, {})
        error = gemini.requests.HTTPError(
            response=SimpleNamespace(status_code=status, headers=headers_)
        )
        return SimpleNamespace(raise_for_status=lambda: (_ for _ in ()).throw(error))

    monkeypatch.setattr(gemini.requests, "post", fake_post)
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    return calls


def _call_ignoring_http_errors():
    try:
        return gemini.generate_text("hi")
    except gemini.requests.HTTPError:
        return None


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")


def test_three_consecutive_429s_open_the_breaker(monkeypatch):
    calls = _script(monkeypatch, [429, 429, 429])

    for _ in range(3):
        _call_ignoring_http_errors()
    assert gemini.rate_limited() is True

    with pytest.raises(gemini.GeminiRateLimited):
        gemini.generate_text("hi")
    with pytest.raises(gemini.GeminiRateLimited):
        gemini.transcribe_audio(b"abc", "audio/wav")
    assert len(calls) == 3  # nothing was sent while open


def test_fewer_than_three_in_a_row_does_not_trip_and_success_resets(monkeypatch):
    _script(monkeypatch, [429, 429, "ok", 429, 429, "ok"])

    results = [_call_ignoring_http_errors() for _ in range(6)]

    assert results == [None, None, "ok", None, None, "ok"]
    assert gemini.rate_limited() is False


def test_other_errors_do_not_trip_the_breaker(monkeypatch):
    _script(monkeypatch, [500] * 9 + [404] * 3)

    for _ in range(6):
        _call_ignoring_http_errors()

    assert gemini.rate_limited() is False


def test_retry_after_header_sets_the_cooldown_and_is_capped(monkeypatch):
    _script(monkeypatch, [(429, {"Retry-After": "120"})] * 3)
    for _ in range(3):
        _call_ignoring_http_errors()
    assert 115 <= gemini.rate_limit_retry_after() <= 120

    monkeypatch.setattr(gemini, "_consecutive_rate_limits", 0)
    monkeypatch.setattr(gemini, "_paused_until", 0.0)
    _script(monkeypatch, [(429, {"Retry-After": "99999"})] * 3)
    for _ in range(3):
        _call_ignoring_http_errors()
    assert gemini.rate_limit_retry_after() <= gemini.MAX_RATE_LIMIT_COOLDOWN_SECONDS


def test_missing_or_invalid_retry_after_uses_the_default_cooldown(monkeypatch):
    _script(monkeypatch, [(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})] * 3)
    for _ in range(3):
        _call_ignoring_http_errors()

    assert 55 <= gemini.rate_limit_retry_after() <= gemini.DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS


def test_calls_resume_after_the_cooldown_and_success_closes_the_breaker(monkeypatch):
    calls = _script(monkeypatch, [429, 429, 429, "ok"])
    for _ in range(3):
        _call_ignoring_http_errors()
    assert gemini.rate_limited() is True

    monkeypatch.setattr(gemini, "_paused_until", time.monotonic() - 1)  # cooldown over

    assert gemini.generate_text("hi") == "ok"
    assert gemini.rate_limited() is False
    assert gemini._consecutive_rate_limits == 0
    assert len(calls) == 4


def test_a_429_right_after_the_cooldown_reopens_it_immediately(monkeypatch):
    _script(monkeypatch, [429, 429, 429, 429])
    for _ in range(3):
        _call_ignoring_http_errors()
    monkeypatch.setattr(gemini, "_paused_until", time.monotonic() - 1)

    _call_ignoring_http_errors()  # the probe call also gets a 429

    assert gemini.rate_limited() is True


def test_cooldown_zero_disables_the_breaker(monkeypatch):
    monkeypatch.setenv("GEMINI_RATE_LIMIT_COOLDOWN_SECONDS", "0")
    calls = _script(monkeypatch, [429] * 6)

    for _ in range(6):
        _call_ignoring_http_errors()

    assert gemini.rate_limited() is False
    assert len(calls) == 6


def test_open_breaker_does_not_spend_daily_quota(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "10")
    _script(monkeypatch, [429, 429, 429])
    for _ in range(3):
        _call_ignoring_http_errors()
    assert client.get("/api/usage").json()["calls"] == 3

    for _ in range(5):
        with pytest.raises(gemini.GeminiRateLimited):
            gemini.generate_text("hi")

    usage = client.get("/api/usage").json()
    assert usage["calls"] == 3
    assert usage["rate_limited"] is True


def test_features_fall_back_quietly_while_the_breaker_is_open(
    client, monkeypatch, caplog  # noqa: F811
):
    # The client fixture clears the key; this test needs AI to look configured.
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    calls = _script(monkeypatch, [429, 429, 429])
    for _ in range(3):
        _call_ignoring_http_errors()
    calls.clear()
    client.post("/api/items", json={"raw_text": "Call the dentist about the crown"})

    with caplog.at_level(logging.DEBUG):
        analysis = client.post("/api/analyze")
        ask = client.post("/api/ask", json={"question": "What about the dentist?"})
        voice = voice_extract.transcribe_audio(
            b"abc", original_filename="m.wav", mime_type="audio/wav"
        )

    assert analysis.status_code == 200
    assert analysis.json()["mode"] == "fallback_after_api_error"
    assert ask.status_code == 200
    assert ask.json()["mode"] != "llm_grounded"
    assert voice["available"] is False
    assert "busy" in voice["note"]
    assert calls == []
    # An expected pause is a warning, not an error with a stack trace.
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_healthz_and_usage_report_the_pause_and_stay_ready(client, monkeypatch):  # noqa: F811
    _script(monkeypatch, [429, 429, 429])
    for _ in range(3):
        _call_ignoring_http_errors()

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["gemini"]["rate_limited"] is True
    assert client.get("/api/usage").json()["rate_limited"] is True
