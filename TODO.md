# TODO

Recommended work, roughly in priority order. Check items off and move them to
`docs/CHANGELOG.md` when they ship. Constraints from AGENTS.md apply: no vector
DB, no new frontend framework, schema changes via Alembic, external actions need
explicit user confirmation, and AI-inferred content stays labelled.

## Finish what is half-built
- [ ] **Persist embeddings.** Store vectors (blob column keyed by item id, text
      hash and model name) so restarts do not re-embed the inbox and relations
      update incrementally. Add tests for cache invalidation on text edit and
      model change. Needs an Alembic migration.
- [ ] **Real image understanding.** `describe_image` in `app/capture/image_extract.py`
      checks for a key and then always returns the fallback. Send the image to
      Gemini inline (same `_post` path as audio) and label the result AI-inferred.
- [ ] **Real calendar integration.** `app/integrations/calendar.py` only does
      preview and mock confirm. Add Google Calendar behind the existing explicit
      confirmation flow.

## Improve quality
- [ ] **Feedback loop on links.** Record dismiss/confirm on relations, add a
      "link these" action, and use the data to re-tune the 0.40 cutoff
      (current recall is 0.50 to 0.65).
- [ ] **Search eval set.** Labelled queries to measure the keyword weights
      (0.30 / 0.55) and the Ask threshold (0.19), mirroring `scripts/eval_linking.py`.
- [ ] **Ask regression fixtures.** Question and expected-source pairs so prompt or
      `GEMINI_MODEL` changes cannot silently degrade answers.

## New capabilities
- [ ] **Auto-tags and clustering** from the embeddings; suggestions stay
      AI-inferred until the user confirms.
- [ ] **Weekly digest** built on `/api/briefing`. Email or push delivery is an
      external action and must be opt-in.
- [ ] **Capture shortcuts:** browser extension or phone share target calling
      `POST /api/items/url`.
- [ ] **Export and restore:** JSON/Markdown export and a documented restore,
      since migrations deliberately disable downgrade.

## Operations
- [ ] **Gemini cost and rate controls:** per-user daily cap, call-count logging,
      circuit breaker after repeated 429s.
- [ ] **`/healthz`:** report DB reachability, whether the embedding model loaded,
      and whether a Gemini key is configured.

## Multi-user concurrency
- [ ] **SQLite settings:** enable WAL and a `busy_timeout` (no `journal_mode` or
      `busy_timeout` is set today), or document Postgres as required for more
      than one active user.
- [ ] **One analysis run per user at a time.** `start_analysis_run` does not check
      for a running run, so a double click starts two Gemini calls and two
      writers. Reject or reuse the in-flight run.
- [ ] **Global cap on concurrent Gemini calls** (semaphore) so slow calls with
      retries cannot exhaust the threadpool.
- [ ] **Fix the embedding cache race.** `_cache` in `app/retrieval/embeddings.py`
      is mutated without the lock, and `_cache.clear()` during another request's
      lookup raises `KeyError`, which is caught and silently becomes a fallback.
- [ ] **Concurrency test:** N users doing capture, search and analyze in parallel
      against a temp DB, asserting no cross-user data and no lock errors.
- [ ] **Per-item edit conflicts** (version or `updated_at` check) for the same
      user editing from two tabs or devices.
