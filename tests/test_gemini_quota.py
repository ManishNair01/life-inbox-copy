"""Per-user daily Gemini call quota."""

import sys
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import gemini
from tests.test_api import client  # noqa: F401  (fixture: isolated temp DB)


def _fake_gemini_http(monkeypatch, text="ok"):
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append(1)
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"candidates": [{"content": {"parts": [{"text": text}]}}]},
        )

    monkeypatch.setattr(gemini.requests, "post", fake_post)
    return calls


def _login(http, email):
    response = http.post("/api/auth/dev-login", json={"email": email})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_calls_past_the_daily_limit_are_refused_without_hitting_the_api(
    client, monkeypatch  # noqa: F811
):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "3")
    http_calls = _fake_gemini_http(monkeypatch)

    assert [gemini.generate_text("hi") for _ in range(3)] == ["ok"] * 3
    with pytest.raises(gemini.GeminiQuotaExceeded):
        gemini.generate_text("hi")

    assert len(http_calls) == 3


def test_retries_inside_one_call_count_once(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "2")
    monkeypatch.setattr(gemini.time, "sleep", lambda _s: None)
    attempts = []

    def flaky_post(url, headers, json, timeout):
        attempts.append(1)
        if len(attempts) < 3:
            raise gemini.requests.ConnectionError()
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
        )

    monkeypatch.setattr(gemini.requests, "post", flaky_post)

    assert gemini.generate_text("hi") == "ok"
    assert len(attempts) == 3
    assert client.get("/api/usage").json()["calls"] == 1


def test_quota_is_per_user(client, monkeypatch):  # noqa: F811
    from app import database

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "1")
    _fake_gemini_http(monkeypatch)

    # Direct calls bypass the request middleware, so bind the owner explicitly.
    alice = _login(client, "quota-a@example.com")
    bob = _login(client, "quota-b@example.com")
    try:
        database.set_current_owner_id(alice)
        assert gemini.generate_text("hi") == "ok"
        with pytest.raises(gemini.GeminiQuotaExceeded):
            gemini.generate_text("hi")

        database.set_current_owner_id(bob)
        assert gemini.generate_text("hi") == "ok"
        assert database.get_ai_usage(1)["remaining"] == 0

        database.set_current_owner_id(alice)
        assert database.get_ai_usage(1)["calls"] == 1
    finally:
        database.set_current_owner_id(None)


def test_quota_resets_on_a_new_utc_day(client, monkeypatch):  # noqa: F811
    from app import database

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "1")
    _fake_gemini_http(monkeypatch)

    monkeypatch.setattr(database, "_utc_day", lambda: "2030-01-01")
    assert gemini.generate_text("hi") == "ok"
    with pytest.raises(gemini.GeminiQuotaExceeded):
        gemini.generate_text("hi")

    monkeypatch.setattr(database, "_utc_day", lambda: "2030-01-02")
    assert gemini.generate_text("hi") == "ok"


def test_limit_zero_disables_the_quota_and_the_usage_table_is_untouched(
    client, monkeypatch  # noqa: F811
):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "0")
    _fake_gemini_http(monkeypatch)

    for _ in range(10):
        assert gemini.generate_text("hi") == "ok"

    usage = client.get("/api/usage").json()
    assert usage["calls"] == 0
    assert usage["limit"] is None and usage["remaining"] is None


def test_simultaneous_calls_never_exceed_the_limit(client, monkeypatch):  # noqa: F811
    from app import database

    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "5")
    owner = database.require_owner_id()
    allowed = []
    guard = threading.Lock()
    barrier = threading.Barrier(12)

    def worker():
        database.set_current_owner_id(owner)
        barrier.wait()
        result = database.try_consume_ai_call(5)
        with guard:
            allowed.append(result)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert allowed.count(True) == 5
    assert allowed.count(False) == 7
    assert database.get_ai_usage(5)["calls"] == 5


def test_usage_endpoint_reports_calls_limit_and_remaining(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "4")
    _fake_gemini_http(monkeypatch)
    gemini.generate_text("hi")

    usage = client.get("/api/usage").json()

    assert usage["calls"] == 1
    assert usage["limit"] == 4
    assert usage["remaining"] == 3
    assert usage["day"]


def test_exhausted_quota_degrades_each_feature_to_its_fallback(
    client, monkeypatch  # noqa: F811
):
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "1")
    http_calls = _fake_gemini_http(monkeypatch, text="not json")
    gemini.generate_text("use up the allowance")
    http_calls.clear()

    client.post("/api/items", json={"raw_text": "Call the dentist about the crown"})

    analysis = client.post("/api/analyze")
    assert analysis.status_code == 200
    assert analysis.json()["mode"] == "fallback_after_api_error"

    ask = client.post("/api/ask", json={"question": "What about the dentist?"})
    assert ask.status_code == 200
    assert ask.json()["mode"] != "llm_grounded"

    from app.capture import voice_extract

    voice = voice_extract.transcribe_audio(
        b"abc", original_filename="m.wav", mime_type="audio/wav"
    )
    assert voice["available"] is False
    assert "limit" in voice["note"]

    assert http_calls == []


def test_quota_check_failure_fails_open(client, monkeypatch):  # noqa: F811
    from app import database

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "1")
    _fake_gemini_http(monkeypatch)

    def broken(limit):
        raise RuntimeError("usage table missing")

    monkeypatch.setattr(database, "try_consume_ai_call", broken)

    assert gemini.generate_text("hi") == "ok"


def test_each_user_gets_their_own_allowance_in_parallel(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "2")
    _fake_gemini_http(monkeypatch)
    app = sys.modules["app.main"].app
    outcomes = {}

    def user(index):
        with TestClient(app) as http:
            _login(http, f"par{index}@example.com")
            # The endpoint path exercises the real per-request owner binding.
            http.post("/api/items", json={"raw_text": f"note {index}"})
            outcomes[index] = [http.post("/api/analyze").status_code for _ in range(1)]
            outcomes[index].append(http.get("/api/usage").json())

    threads = [threading.Thread(target=user, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)

    assert set(outcomes) == {0, 1, 2, 3}
    for status, usage in outcomes.values():
        assert status == 200
        assert usage["calls"] <= 2


def test_usage_reports_whether_ai_is_enabled(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "4")
    assert client.get("/api/usage").json()["ai_enabled"] is False

    monkeypatch.setenv("GEMINI_API_KEY", "secret")
    assert client.get("/api/usage").json()["ai_enabled"] is True
