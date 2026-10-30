import pytest


@pytest.fixture(autouse=True)
def _no_real_gemini_key(monkeypatch):
    """app/__init__ loads .env; keep tests from ever seeing a real key."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_gemini_quota(monkeypatch):
    """Quota accounting writes to the database; quota tests opt back in."""
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "0")


@pytest.fixture(autouse=True)
def _offline_embeddings(monkeypatch):
    """Keep tests deterministic and offline; embedding tests opt back in."""
    monkeypatch.setenv("LIFE_INBOX_DISABLE_EMBEDDINGS", "1")
