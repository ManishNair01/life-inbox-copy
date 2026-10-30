import importlib
import sys
import threading

import pytest
from sqlalchemy import text


@pytest.fixture()
def database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'wal.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    sys.modules.pop("app.database", None)
    module = importlib.import_module("app.database")
    yield module
    module.engine.dispose()
    sys.modules.pop("app.database", None)


def _pragma(database, name):
    with database.engine.connect() as connection:
        return connection.execute(text(f"PRAGMA {name}")).scalar()


def test_sqlite_connections_use_wal_busy_timeout_and_foreign_keys(database):
    assert str(_pragma(database, "journal_mode")).lower() == "wal"
    assert _pragma(database, "busy_timeout") == database.SQLITE_BUSY_TIMEOUT_MS
    assert _pragma(database, "foreign_keys") == 1


def test_parallel_writers_and_readers_do_not_hit_database_locked(database):
    with database.engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS probe (n INTEGER)"))

    errors = []

    def write(worker):
        try:
            for i in range(25):
                with database.engine.begin() as connection:
                    connection.execute(
                        text("INSERT INTO probe (n) VALUES (:n)"),
                        {"n": worker * 100 + i},
                    )
        except Exception as exc:  # noqa: BLE001 - collected for the assertion
            errors.append(exc)

    def read():
        try:
            for _ in range(50):
                with database.engine.connect() as connection:
                    connection.execute(text("SELECT COUNT(*) FROM probe")).scalar()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(w,)) for w in range(6)]
    threads += [threading.Thread(target=read) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    with database.engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM probe")).scalar() == 150
