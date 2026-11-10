"""The privacy page says who processes users' content (change 007)."""

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

MODULES = ("app.main", "app.database", "app.auth", "app.config")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'privacy.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    with TestClient(main.app) as test_client:
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def test_privacy_page_names_nvidia_as_the_ai_provider(client):
    page = client.get("/privacy")
    assert page.status_code == 200
    text = page.text
    assert "NVIDIA" in text
    # The old draft said content "may be sent to OpenAI"; NVIDIA is the provider now.
    assert "may be sent to OpenAI" not in text
    for use in ("Organizing a note", "Voice memos", "Ask My Inbox", "Creating a topic"):
        assert use in text
    assert "password are never sent" in text


def test_privacy_page_explains_link_fetching(client):
    text = client.get("/privacy").text
    assert "Links you save" in text
    assert "fetches that page" in text
    assert "YouTube" in text


def test_privacy_page_discloses_ai_usage_records(client):
    text = client.get("/privacy").text
    assert "AI usage records" in text
    assert "Never the text that was sent or returned" in text
