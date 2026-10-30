import pytest
from sqlalchemy import text

from app import gemini, health
from app.retrieval import embeddings
from tests.test_api import client  # noqa: F401  (fixture: isolated temp DB)

EXPECTED_KEYS = {"status", "database", "schema", "embeddings", "gemini"}


def test_healthz_reports_ready_without_authentication(client):  # noqa: F811
    response = client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == EXPECTED_KEYS
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    # Tests build the schema without Alembic, so there is no version to compare.
    assert body["schema"] == "unknown"
    assert body["embeddings"] == "disabled"
    assert body["gemini"] == {"configured": False, "daily_limit_per_user": None}


def test_healthz_never_exposes_secrets_or_error_text(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key-value")
    monkeypatch.setenv("GEMINI_DAILY_CALL_LIMIT", "25")

    body = client.get("/healthz").text

    assert "super-secret-key-value" not in body
    assert client.get("/healthz").json()["gemini"] == {
        "configured": True,
        "daily_limit_per_user": 25,
    }


def test_healthz_has_no_side_effects(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("GEMINI_API_KEY", "secret")

    def forbidden(*args, **kwargs):
        raise AssertionError("healthz must not do this")

    monkeypatch.setattr(embeddings, "_load_model", forbidden)
    monkeypatch.setattr(gemini, "_post", forbidden)
    monkeypatch.setattr(gemini, "_charge_quota", forbidden)

    assert client.get("/healthz").status_code == 200
    usage = client.get("/api/usage").json()
    assert usage["calls"] == 0


def test_healthz_returns_503_not_500_when_database_is_down(client, monkeypatch):  # noqa: F811
    from app import database

    def down(*args, **kwargs):
        raise RuntimeError("connection refused: postgres://user:pw@db/secret")

    monkeypatch.setattr(database.engine, "connect", down)

    response = client.get("/healthz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["database"] == "error"
    assert "postgres" not in response.text and "refused" not in response.text


def _stamp_version(version):
    from app import database

    with database.engine.begin() as connection:
        connection.execute(
            text("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))")
        )
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:v)"),
            {"v": version},
        )


def test_healthz_is_unavailable_when_schema_is_behind_this_build(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(health, "_expected_head", "0099_future")
    _stamp_version("0001_old")

    response = client.get("/healthz")

    assert response.status_code == 503
    assert response.json()["schema"] == "behind"
    assert response.json()["status"] == "unavailable"


def test_healthz_is_ok_when_schema_matches_head(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(health, "_expected_head", "0099_future")
    _stamp_version("0099_future")

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["schema"] == "current"


def test_healthz_is_degraded_but_ready_when_embeddings_failed(client, monkeypatch):  # noqa: F811
    monkeypatch.setattr(embeddings, "status", lambda: "unavailable")

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["embeddings"] == "unavailable"


def test_migration_head_is_read_from_the_shipped_scripts(monkeypatch):
    monkeypatch.setattr(health, "_expected_head", None)
    monkeypatch.setattr(health, "_head_lookup_failed", False)

    assert health._migration_head()


def test_embedding_status_values(monkeypatch):
    monkeypatch.setenv("LIFE_INBOX_DISABLE_EMBEDDINGS", "1")
    assert embeddings.status() == "disabled"

    monkeypatch.delenv("LIFE_INBOX_DISABLE_EMBEDDINGS")
    monkeypatch.setattr(embeddings, "_model", None)
    monkeypatch.setattr(embeddings, "_load_failed", False)
    assert embeddings.status() == "not_loaded"

    monkeypatch.setattr(embeddings, "_load_failed", True)
    assert embeddings.status() == "unavailable"

    monkeypatch.setattr(embeddings, "_model", object())
    assert embeddings.status() == "ready"
