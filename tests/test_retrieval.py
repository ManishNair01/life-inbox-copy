import importlib
import sys

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_db_path = tmp_path / "life_inbox_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    sys.modules.pop("app.database", None)
    sys.modules.pop("app.main", None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")

    with TestClient(main.app) as test_client:
        yield test_client

    database.engine.dispose()
    sys.modules.pop("app.main", None)
    sys.modules.pop("app.database", None)


def test_search_finds_keyword_matches(client):
    client.post("/api/items", json={"raw_text": "Renew car insurance before March 15"})
    client.post(
        "/api/items",
        json={"raw_text": "Try the Gurgaon restaurant Rohan recommended"},
    )

    hits = client.get("/api/search", params={"q": "car insurance"}).json()
    assert hits
    assert any("insurance" in hit["excerpt"].lower() for hit in hits)
    assert hits[0]["item_id"] > 0


def test_ask_returns_citations_for_known_question(client):
    created = client.post(
        "/api/items",
        json={"raw_text": "Order Atomic Habits this weekend after Rohan's recommendation"},
    ).json()

    response = client.post(
        "/api/ask",
        json={"question": "What did Rohan recommend about Atomic Habits?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["confidence"] != "insufficient"
    assert data["citations"]
    assert any(cite["item_id"] == created["id"] for cite in data["citations"])
    assert "Atomic Habits" in data["answer"]


def test_ask_admits_insufficient_evidence(client):
    client.post("/api/items", json={"raw_text": "Buy milk tomorrow"})

    data = client.post(
        "/api/ask",
        json={"question": "What is the capital of France?"},
    ).json()
    assert data["confidence"] == "insufficient"
    assert data["citations"] == []
    assert "enough" in data["answer"].lower()
