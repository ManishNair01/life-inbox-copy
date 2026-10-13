# Architecture

## Stack

- **API:** FastAPI
- **ORM:** SQLAlchemy
- **Migrations:** Alembic (authoritative schema owner)
- **DB:** SQLite locally (temp/test DBs for development)
- **UI:** HTML + vanilla JS/CSS
- **AI:** OpenAI optional; deterministic fallback organizer always available

## Core modules

| Module | Responsibility |
| --- | --- |
| `app/main.py` | HTTP routes, error shaping |
| `app/database.py` | Models, persistence helpers, fingerprints, task upsert |
| `app/schemas.py` | Request/response and analysis contracts |
| `app/organizer.py` | OpenAI + fallback organization |
| `app/capture/` | Rich capture (URL, PDF, image, voice, lifecycle) |
| `app/templates` / `app/static` | Browser UI |

## Data model (current)

- `inbox_items` — canonical captures
- `notes` — legacy safety copy (not authoritative)
- `topics` — user-editable spaces/projects (seeded defaults)
- `analysis_runs` — analyze attempts + JSON result (includes inbox fingerprint)
- `item_insights` — AI category/title/priority/tags/rationale/topic plus user overrides
- `item_relations` — duplicate / near-duplicate / related pairs (dismissible)
- `tasks` / `task_source_items` — durable tasks; multiple tasks per source allowed;
  AI vs confirmed timing distinguished

## Analysis freshness

Successful analysis stores an `inbox_fingerprint` hash of inbox content.
`GET /api/analyze/latest` recomputes the hash and sets `is_stale` when the
inbox has changed since that run.

## Schema evolution

1. Change SQLAlchemy models
2. Add an Alembic revision under `migrations/versions/`
3. `alembic upgrade head` on empty and previous-milestone DBs in the quality gate

`LIFE_INBOX_AUTO_CREATE_TABLES=1` is allowed only for isolated automated tests.

## Rich capture lifecycle

URL, PDF, image, and voice captures follow: **capture → save original →
process → extract → organize → ready/failed**.

- Original sources are persisted before extraction (`source_url` or `storage_path`).
- `processing_status`: `captured`, `processing`, `ready`, `failed`.
- `POST /api/items/{id}/retry` re-runs processing for failed capture items.
- Images: OCR text in `extracted_text` (editable facts); AI copy in
  `ai_description` (inferred). Thumbnails via `?variant=thumb`.
- Voice: original audio retained; transcript in `extracted_text` (editable);
  browser MediaRecorder upload supported when the mic is available.
- Ready captures feed organization via `list_notes_from_db()` (uses `extracted_text`).

Uploads default to `data/uploads/` (override with `LIFE_INBOX_UPLOAD_DIR`).
OCR/vision/transcription adapters degrade gracefully when not configured
(`LIFE_INBOX_DISABLE_OCR=1`, `LIFE_INBOX_DISABLE_TRANSCRIPTION=1` for tests).

## External services

Automated tests mock OpenAI and must not call paid APIs. Live calls are for
explicit manual smoke testing only.
