# Changelog

Newest first. This entry covers the uncommitted work on `feat/gemini-backend`
(on top of Milestone 6 plus the OpenAI voice wiring).

## Unreleased — `feat/gemini-backend`

### Changed: AI provider moved from OpenAI to Gemini
- New `app/gemini.py`: a small REST client for text generation and audio
  transcription (60 s timeout, 3 attempts with backoff on 5xx; 429 is not retried).
- `app/organizer.py`: `analyze_inbox_with_openai` is now `analyze_inbox_with_gemini`;
  analysis `mode` is `"gemini"` (`"openai"` stays valid in the schema for old rows).
- `app/retrieval/ask.py`, `app/capture/image_extract.py`,
  `app/capture/voice_extract.py`, `scripts/seed_demo_notes.py` use the Gemini
  client. Voice transcription provider is reported as `gemini`.
- Config: `GEMINI_API_KEY` (or `GOOGLE_API_KEY`), `GEMINI_MODEL`
  (default `gemini-3.5-flash`), optional `GEMINI_TRANSCRIPTION_MODEL`.
  `OPENAI_*` variables and the `openai` dependency are gone.
- `app/__init__.py` now calls `load_dotenv()`; real environment variables win.
- Every path still falls back to the deterministic/extractive behaviour when no
  key is set or the API fails.

### Added: local embeddings (not a vector DB)
- New `app/retrieval/embeddings.py`: local sentence embeddings via `fastembed`
  (ONNX, model `BAAI/bge-small-en-v1.5`), no API or quota. Thread-safe lazy load,
  in-process cache (20,000 texts), and a rescaled similarity (cosine floor 0.45).
  If the model cannot load, callers get `None` and fall back to lexical scoring.
- Config: `LIFE_INBOX_EMBEDDING_MODEL`, `LIFE_INBOX_DISABLE_EMBEDDINGS=1`.
- Embeddings are computed on demand and cached in memory only; nothing is
  stored in the database, and no vector database was introduced.

### Added: semantic similarity linking
- `app/similarity.py`: "related" links now use embedding similarity with a 0.40
  cutoff (best F1 on both labelled sets). Duplicate and near-duplicate detection
  stays lexical. A title is embedded only when it adds text beyond the body
  (repeating it raised false links from 4 to 20 on the held-out set).
- Each relation carries a `method`: `lexical` (text overlap) or `semantic`
  (AI-inferred). Exposed through `ItemRelation.method` and `GET /api/relations`.
- Migration `0012_relation_method` adds `item_relations.method`
  (default `lexical`, so existing rows stay correct). **Downgrade is disabled**
  on purpose to avoid dropping provenance; restore from backup to roll back.
- UI (`app/static/app.js`): related items show "AI-inferred" or "text match"
  with the score.
- Evaluation: `scripts/eval_linking.py` with `tests/fixtures/linking_eval_notes.csv`
  and `linking_eval_notes_heldout.csv`; write-up in `docs/semantic-linking.md`.

| Set | Precision | Recall | F1 | Original scorer F1 |
| --- | --- | --- | --- | --- |
| First (52 notes) | 0.857 | 0.500 | 0.632 | 0.121 |
| Held-out (47 notes) | 0.733 | 0.647 | 0.688 | 0.182 |

### Changed: search and Ask scoring
- `app/retrieval/search.py`: passages are scored with embeddings when available.
  Keyword weight is 0.30 with embeddings and 0.55 with the TF-IDF fallback.
  The fallback query vector is now IDF-weighted and drops terms absent from the
  corpus, which previously deflated every score.
- `app/retrieval/ask.py`: "insufficient evidence" threshold lowered from 0.20 to 0.19.

### Added: one analysis per user at a time
- Migration `0013_one_running_analysis`: partial unique index so a user can have only
  one `running` analysis, enforced by the DB across threads and workers. Existing
  `running` rows are marked failed when migrating.
- `POST /api/analyze` returns 409 if one is already running; runs left `running`
  for over 10 minutes are treated as crashed and expired.

### Fixed: embedding cache race
- `embed_passages` now guards the shared cache with a lock and reads from a local
  snapshot, so one request clearing the cache can no longer raise `KeyError` in
  another and silently degrade it to keyword search.

### Changed: SQLite concurrency settings
- Every SQLite connection now sets WAL journal mode, a 5 s `busy_timeout` and
  foreign keys. `docs/deployment.md` documents backups of the WAL files and when
  to move to Postgres.

### Added: edit-conflict detection (optimistic concurrency)
- Migration `0014_item_version` adds `inbox_items.version` (default 1). It is bumped
  by user edits and by any ORM write that changes `raw_text`, `extracted_text` or
  `ai_description` (capture retries, extraction), and returned as `InboxItem.version`.
- `PUT /api/items/{id}` and `PATCH /api/items/{id}/extracted-text` accept an optional
  `expected_version`. The write is a single conditional UPDATE, so it is atomic across
  threads and workers; on mismatch the API returns 409 with
  `detail: {code: "version_conflict", message, current}`. Without `expected_version`
  (older clients, `/api/notes`) the edit is last-write-wins but still bumps the version.
- UI: a 409 keeps the typed text and tells the user; the next Save overwrites knowingly.
- `update_item_extracted_text` now also checks ownership itself (the API layer already did).

### Added: per-user Gemini daily quota
- Migration `0015_ai_usage` and an `ai_usage` table (user, UTC day, calls).
- `GEMINI_DAILY_CALL_LIMIT` (default 100 per user per UTC day, `0` disables). One
  conditional UPDATE both checks and increments, so concurrent requests cannot go
  over the limit. A call counts once even when retried; failed calls still count.
- Past the limit `generate_text` and `transcribe_audio` raise `GeminiQuotaExceeded`
  without contacting the API; analysis, Ask and voice use their fallbacks, and voice
  notes explain the limit was reached. If the usage table is unreadable the call is
  allowed (cost control, not security) and a warning is logged.
- `GET /api/usage` reports `day`, `calls`, `limit`, `remaining` and `ai_enabled` for the
  signed-in user.
- UI: usage line under the Analyze button, a warning banner at the limit, and fresh
  Analyze/Ask results state when they used basic methods because of the limit. The
  line is hidden when no key or no limit is set, and fallbacks are only attributed to
  the limit when AI is enabled (checked in a browser).
- Tests stay off the usage table by default (`GEMINI_DAILY_CALL_LIMIT=0` in conftest).

### Tests
- New: `tests/conftest.py` (clears Gemini keys, disables embeddings by default),
  `tests/test_gemini.py`, `tests/test_gemini_failures.py` (blocked/empty responses,
  voice fallback, API key never logged), `tests/test_embedding_fallback.py` (model
  load failure, runtime errors, TF-IDF and lexical-relation fallbacks),
  `tests/test_search_scoring.py`,
  `tests/test_semantic_relations.py`. Updated: `test_api.py`, `test_retrieval.py`,
  `test_migrations.py`, `test_pagination_state.py`.
- `tests/test_concurrency.py` (5 users in parallel, no collisions or leaks),
  `tests/test_sqlite_settings.py` (WAL, busy timeout, parallel writers).
- `tests/test_edit_conflicts.py` (stale edits, simultaneous edits, ORM bumps, ownership).
- `tests/test_gemini_quota.py` (limit, per-user, daily reset, atomicity, fallbacks).
- Suite: 176 passed with `GEMINI_API_KEY` unset.

### Repo hygiene
- `requirements.txt` uses compatible-release pins; `pytest` and `httpx` moved to
  the new `requirements-dev.txt` (used by CI, README and AGENTS.md).
- `.gitignore` covers `data/*.db*` (DB backups); new `.gitattributes` normalises
  line endings to LF.
- `docs/deployment.md`: new "AI and embedding model (first run)" section covering
  the model download, cache location, offline warm-up and fallbacks.
- Docs updated: `README.md`, `AGENTS.md`, `docs/architecture.md`,
  `docs/deployment.md`, `docs/manual-testing.md`.

## Earlier history
See `docs/milestone-status.md` for Milestones 1–6 and the Session 7A/7C commits.
