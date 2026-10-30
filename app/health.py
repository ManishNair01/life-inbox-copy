"""Readiness report for /healthz.

Safe to expose without authentication: it reports only whether things work,
never keys, versions, paths, error text or user data. It must never trigger
work with side effects (no model download, no Gemini call).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from app import gemini
from app.retrieval import embeddings

logger = logging.getLogger(__name__)

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

_expected_head: Optional[str] = None
_head_lookup_failed = False


def _migration_head() -> Optional[str]:
    """Newest revision shipped with this build (read once from the scripts)."""
    global _expected_head, _head_lookup_failed
    if _expected_head is None and not _head_lookup_failed:
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory

            config = Config(str(ALEMBIC_INI))
            config.set_main_option("script_location", str(ALEMBIC_INI.parent / "migrations"))
            _expected_head = ScriptDirectory.from_config(config).get_current_head()
        except Exception:
            logger.warning("Could not read the migration head", exc_info=True)
            _head_lookup_failed = True
    return _expected_head


def _check_database() -> tuple[str, str]:
    """Return (database status, schema status)."""
    from app.database import engine

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            try:
                current = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
            except Exception:
                # No alembic_version table: schema built outside Alembic
                # (automated tests). Not something to fail readiness over.
                return "ok", "unknown"
    except Exception:
        logger.warning("Health check: database unreachable", exc_info=True)
        return "error", "unknown"

    head = _migration_head()
    if head is None or current is None:
        return "ok", "unknown"
    return "ok", "current" if current == head else "behind"


def readiness() -> tuple[dict, bool]:
    """Return (report, ready). ``ready`` False means serve a 503."""
    database, schema = _check_database()
    embedding_status = embeddings.status()
    limit = gemini.daily_call_limit()

    ready = database == "ok" and schema != "behind"
    if not ready:
        status = "unavailable"
    elif embedding_status == "unavailable":
        status = "degraded"
    else:
        status = "ok"

    return (
        {
            "status": status,
            "database": database,
            "schema": schema,
            "embeddings": embedding_status,
            "gemini": {
                "configured": gemini.api_key() is not None,
                "daily_limit_per_user": limit if limit > 0 else None,
            },
        },
        ready,
    )
