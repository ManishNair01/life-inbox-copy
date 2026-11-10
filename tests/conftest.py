import sys

import pytest

# Tests reload app.main and app.database for each test (a fresh temporary
# database). These modules hold a reference to app.database, so they must be
# reloaded with it, or they would keep talking to an earlier test's database.
RELOADED_WITH_THE_DATABASE = ("app.captain", "app.filing")


@pytest.fixture(autouse=True)
def clean_ai_keys_env(monkeypatch):
    """Ensure automated tests never leak host API keys or make paid/live network calls."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def no_oembed_requests(monkeypatch):
    """Link cards (change 015) ask YouTube or Vimeo for a video's title. Tests
    never reach the internet: a test that wants an answer fakes _http_get."""
    from app.capture import link_card

    def offline(url, timeout=6.0):
        raise ConnectionError(f"tests never fetch {url}")

    monkeypatch.setattr(link_card, "_http_get", offline)


@pytest.fixture(autouse=True)
def reload_database_users():
    for name in RELOADED_WITH_THE_DATABASE:
        sys.modules.pop(name, None)
    yield
    for name in RELOADED_WITH_THE_DATABASE:
        sys.modules.pop(name, None)
