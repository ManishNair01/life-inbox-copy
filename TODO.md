# TODO

Recommended work, roughly in priority order. Check items off and move them to
`docs/CHANGELOG.md` when they ship. Constraints from AGENTS.md apply: no vector
DB, no new frontend framework, schema changes via Alembic, external actions need
explicit user confirmation, and AI-inferred content stays labelled.

## Status (branch `feat/gemini-backend`)
Done and committed: Gemini backend, local embeddings and semantic linking,
concurrency hardening (6 of 6), per-user Gemini quota with UI, `/healthz`, and the
429 circuit breaker. The suite passes (196 tests). Nothing is pushed and no PR is
open. Operations has one open item (breaker banner); everything else below is new
feature work.

Suggested next steps, in order:
1. Push the branch and open a PR for review.
2. Persist embeddings (the scaling cliff).
3. Real image understanding (the plumbing already exists).

## Branch and review
- [ ] **Push `feat/gemini-backend` and open a PR** (18 commits ahead of
      `origin/main`, which has since gained 12 commits; a merge currently conflicts in
      7 files, see the draft PR notes). Pushing is outward-facing, so do it only when asked.
- [ ] **Optional: tidy history.** Commit `c9de62a` alone fails to import `app.main`
      because `app/main.py` was fixed in the follow-up `b8e94e3`. Squashing them would
      keep `git bisect` clean, but AGENTS.md forbids history rewrites, so leave it
      unless explicitly approved.

## Not yet verified
- [ ] **Edit-conflict UI in a browser.** Only `node --check` was run on the JS. Open
      one item in two tabs, save in one, then save in the other: expect the conflict
      message, the typed text kept, and the next Save overwriting.
- [ ] **Quota line with no API key** (should be hidden) and **voice upload** with the
      limit reached were not clicked through. The server side is tested.
- [ ] **Docker image build.** Docker is not installed here, so the model prefetch step
      and the `HEALTHCHECK` line have never been built or run in a container. (The
      health-check command itself was run against a live server: exit 0 when ready,
      exit 1 on 503.)
- [ ] **A real Gemini 429.** The breaker is tested with simulated responses only.

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
- [x] **Per-user Gemini daily quota.** `ai_usage` table (migration 0015),
      `GEMINI_DAILY_CALL_LIMIT` (default 100, 0 = off), atomic conditional UPDATE,
      `GET /api/usage`, fallbacks when exhausted.
- [x] **Circuit breaker after repeated 429s.** 3 in a row pause Gemini calls for
      `Retry-After` (capped) or `GEMINI_RATE_LIMIT_COOLDOWN_SECONDS` (default 60);
      quota is not spent while paused; reported in `/api/usage` and `/healthz`.
- [ ] **Show the pause in the UI** (a banner when `/api/usage` says `rate_limited`).
      Check it in a browser as was done for the quota line, and only attribute a
      fresh fallback to the pause when AI is enabled.
- [ ] **Breaker follow-ups (optional).** State is per process, so with several
      workers each learns about a 429 streak on its own (share it via the database if
      that matters). After a cool-down every concurrent call is a probe, not just one;
      add single-probe logic if bursts after a pause become a problem.
- [x] **Quota visibility in the UI.** Usage line under Analyze ("AI usage today: N of
      M calls", "(K left)" near the limit), a warning banner when the limit is reached,
      and fresh Analyze/Ask results say when they used basic methods because of it.
      Hidden when no key or no limit is configured.
- [x] **`/healthz`.** Unauthenticated readiness: database reachable, schema vs the
      build's migration head, embedding state, whether Gemini is configured. 503 when
      the DB is down or the schema is behind; Dockerfile `HEALTHCHECK` uses it.

## Multi-user concurrency
Status: 6 of 6 done.
- [x] **SQLite settings.** WAL plus an explicit 5 s busy timeout (the sqlite3
      driver already defaulted to 5 s, so WAL is the real change). Postgres is
      documented for more than a few active users.
- [x] **One analysis run per user at a time.** Partial unique index (migration
      0013), 409 on conflict, runs expire after 10 min.
- [x] **Global cap on concurrent Gemini calls.** Semaphore,
      `GEMINI_MAX_CONCURRENT` (default 4); callers fall back after a 20 s wait.
      Per-user quotas remain under Operations.
- [x] **Embedding cache race.** Cache has its own lock; lookups use a local snapshot.
- [x] **Concurrency test.** `tests/test_concurrency.py`: 5 users in parallel doing
      capture, analyze, search, Ask and tasks against one temp DB; asserts no
      errors, disjoint ids, and no cross-user data in any response.
- [x] **Per-item edit conflicts.** `inbox_items.version` (migration 0014), bumped on
      every text change; `PUT /api/items/{id}` and `PATCH .../extracted-text` take
      `expected_version` and return 409 with the current item; the UI keeps the
      user's text and makes the next Save an explicit overwrite.
