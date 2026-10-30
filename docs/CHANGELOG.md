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

### Tests
- New: `tests/conftest.py` (clears Gemini keys, disables embeddings by default),
  `tests/test_gemini.py`, `tests/test_gemini_failures.py` (blocked/empty responses,
  voice fallback, API key never logged), `tests/test_embedding_fallback.py` (model
  load failure, runtime errors, TF-IDF and lexical-relation fallbacks),
  `tests/test_search_scoring.py`,
  `tests/test_semantic_relations.py`. Updated: `test_api.py`, `test_retrieval.py`,
  `test_migrations.py`, `test_pagination_state.py`.
- Suite: 145 passed with `GEMINI_API_KEY` unset.

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
