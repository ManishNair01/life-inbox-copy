# AGENTS.md — Life Inbox

Guidance for humans and coding agents working in this repository.

## Operating Directives

- Always read AGENTS.md before coding, and log every change and decision in decision.md as you make it.

## Startup

```bash
python3 -m pip install -r requirements.txt
export DATABASE_URL="sqlite:////absolute/path/to/temp_life_inbox.db"
export LIFE_INBOX_UPLOAD_DIR="/tmp/life_inbox_uploads"
python3 -m alembic upgrade head
python3 -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

Optional AI (NVIDIA NIM is the default provider; OpenAI also works):

```bash
export NVIDIA_API_KEY="nvapi-..."
export NVIDIA_LLM_MODEL="nvidia/nemotron-3.5-bolt-e4b"
# or instead: export OPENAI_API_KEY="..."; export OPENAI_MODEL="gpt-5-mini"
# optional: seconds before an AI request gives up (default 60)
export LIFE_INBOX_AI_TIMEOUT_SECONDS=60
```

## Tests

```bash
unset OPENAI_API_KEY NVIDIA_API_KEY
python3 -m pytest -v --tb=short
```

Tests use isolated temporary SQLite databases via `DATABASE_URL` and set
`LIFE_INBOX_AUTO_CREATE_TABLES=1`. They must not call live paid APIs; mock
OpenAI and other external services.

## Migrations

Alembic is the only schema-management mechanism for real databases.

```bash
python3 -m alembic upgrade head
python3 -m alembic current
```

Do not rely on SQLAlchemy `create_all` outside automated tests.
`LIFE_INBOX_AUTO_CREATE_TABLES` is test-only.

## Architecture boundaries

- FastAPI app in `app/main.py`
- Persistence / domain writes in `app/database.py`
- Pydantic contracts in `app/schemas.py`
- Organization / AI in `app/organizer.py`; filing v2 (change 014) in
  `app/filing.py`: code first (rules R1-R6), one AI call per note (up to 5
  notes saved together), code checks the answer, one repair call, then the
  offline matcher. The AI may only pick existing topics; unsure notes get no
  topic and wait in Needs you (`filing_pending`). There is no catch-all. Tasks
  come only from the user's own words, never a source's text. Only a commitment
  becomes a task; a maybe or someday idea is a `task_ideas` row (change 014a).
- The five life areas ("life bots") in `app/bots.py`: their 3 default topics
  each, the AI's "about" text and the offline keyword rules. Every topic has a
  `bot_key` and an `origin` (built_in, user, ai); `GET /api/bots` lists the
  areas and `?bot=` filters items, tasks, calendar, topics and search.
- Every AI call (LLM and speech-to-text) goes through `app/llm.py`: client,
  model, timeout, prompt-size limits, retries and the `ai_calls` log (sizes
  and outcomes, never prompt text). Never create an `OpenAI` client anywhere
  else; `tests/test_llm.py` checks this.
- Rich capture in `app/capture/` (`POST /api/items/url`, `/pdf`, `/image`, `/voice`).
  Images (021): OCR by Tesseract (`tesseract_cmd()`; the owner installs it), and
  a vision call only for an image with no readable text and no note
  (`needs_vision`). PDFs (022): layout text, OCR for scanned pages via
  pypdfium2, a one-time AI summary for long ones (`inbox_items.source_summary`,
  AI output). Your note on a source is editable (023,
  `PATCH /api/items/{id}/context`), which re-files it;
  link cards in `app/capture/link_card.py` (change 015: tidy links, oEmbed,
  schema.org data, main text; standard library only; text only, never a
  picture or player). Tests never reach the internet: conftest blocks oEmbed.
- Retrieval / Ask in `app/retrieval/` (`GET /api/search`, `POST /api/ask`).
  Ask me v2 (change 019): evidence is note passages, confirmed memory facts and
  the tasks on the days the question names (`question_period`, code only); no
  AI call when nothing matches; every citation and claim is checked by code
  (`_check_answer`), one repair call, then the quoted answer. Suggested actions
  are made by code and run only when the user taps them.
- Attention / reminders in `app/attention/` (`GET /api/attention`, `/api/briefing`);
  the Dashboard's numbers in `app/attention/glance.py` (`GET /api/dashboard/glance`),
  pure functions with no AI call
- Task priority: `tasks.priority` is the AI's and `tasks.user_priority` yours
  (`PATCH /api/tasks/{id}`); read it through `task_priority()` so yours wins.
  Analysis must never write `user_priority`.
- Task dates: analysis never moves a confirmed date unless the note was edited
  (`tasks.date_recheck`); then it may, unconfirmed, and the UI asks again.
  Record every date change in `task_date_changes` (`_record_date_change`).
  `tasks.due_confidence` says where a date came from: `from_note` (the words
  name the day) goes on `due_on`; `suggested` (a guess) waits in
  `suggested_due_on`, off the calendar and reminders, until you confirm it
  (`user_confirmed`). Set dates through `_apply_timing`, and read them
  relative to the day the note was written (`_written_day`), never today.
- Captain's "Needs you" list in `app/captain.py` (`GET /api/captain/needs-you`,
  `POST /api/captain/needs-you/{id}/resolve`): built by code from the user's
  data, no AI call. A new kind of question is a card builder there. Keep at
  most one card per note, and record answers (`record_captain_answer`) so an
  answered card never comes back.
- Memory (change 016) in `app/database.py` (`remember`, `_remember_in`,
  `list_memory`, `update_memory`, `delete_memory`, `upcoming_plans`) and
  `GET/PATCH/DELETE /api/memory`. Facts come only from the user's own actions
  and words, never a source's text. Write facts through `_remember_in`: it
  refuses secrets, health facts without consent, and facts the user deleted.
- The AI switch (change 025, decision Q) is one gate in `app/llm.py`
  (`allowed()`, registered by `app/database.py` from
  `user_settings.ai_processing`): `is_configured()` is false and
  `complete_text` raises `AiSwitchedOff` when it's off. Never call a provider
  any other way, and keep every feature's no-AI path working.
- Onboarding (change 024): `/api/onboarding`; answers become confirmed
  core-profile facts through `_remember_in`. Account deletion (025):
  `POST /api/auth/account/delete` (password + "DELETE") runs `erase_user`, which
  deletes by table dependency order; a new table with `owner_user_id`,
  `user_id`, `item_id` or `task_id` is covered automatically, so name any other
  per-user column that way too.
- Weekly review, topic proposals, bot summaries and the greeting (change 020)
  in `app/review.py`. AI calls run as background tasks (`BackgroundTasks`) or
  from the scheduler, never while a page waits; each is skipped without AI or
  with `user_settings.ai_processing` off. A proposal never creates a topic by
  itself (P1): only Captain's "Create it" does (`create_topic_from_proposal`).
- Scout (change 018) in `app/scout.py`: code only, no AI. Questions come from
  `database.scout_facts`; answers go through `set_task_status` / `set_task_date`
  with `by="scout"` (they record `task_events`). The dispatcher's weekly push
  uses `scout.push_for` on data it already loaded: never add database access to
  `app/notifications/service.py` paths, since its unit tests run without a test
  database. Someday tasks (`tasks.someday`) have no date; keep them out of
  date-based lists and Captain's cards.
- Memory in filing (change 017) in `app/filing.py` (`memory_pack`, `_memory_fields`),
  only with `LIFE_INBOX_MEMORY_IN_FILING=1` (off by default). Only confirmed
  facts go to the AI, within 1,800 characters; unknown hint ids and bad plan
  updates are dropped, never a repair call. A plan update changes nothing until
  the user answers Captain's "plan" card. Replay: `python -m scripts.memory_replay --live`
  spends AI credits; run it only with the owner's OK.
- Secrets (change 016) in `app/sensitive.py`. Any new path that sends note text
  to the AI must skip or `mask_secrets` it (filing, Ask, organizer and voice
  already do); anything that shows note text uses `secret_masked`.
- Upgrade the owner's database (after a backup) before changing code that needs
  a new migration: a running `--reload` server refuses to start on an old
  schema.
- Calendar adapter in `app/integrations/calendar.py` (preview + mock confirm only)
- Auth / ownership in `app/auth.py` + `users.owner_user_id` scoping.
  Every route except those in `PUBLIC_PATHS` (`app/main.py`) needs a session;
  tests sign in via `tests/auth_helpers.py`. Never add an anonymous fallback.
- Login page: `app/templates/login.html` + `app/static/auth.js`
- Config validation in `app/config.py`; deploy notes in `docs/deployment.md`
  and `docs/deploy-container.md` (container route). Beta/production need
  `LIFE_INBOX_EMAIL_PROVIDER=smtp` (or `off` for a private beta only).
- Browser UI: `app/templates/index.html` (the three-pane app, change 009) and
  `app/static/*`:
  - `shell.js` draws the panes, routes (`#/home`, `#/topics`, `#/topic/<id>`,
    ...), the lens (`?bot=`), Home, Topics and spaces, the topic page and the
    note page;
  - `shell_logic.js` holds its pure logic, tested in Node by
    `tests/test_shell.py`;
  - `shell.css` holds the layout and the calm theme (`data-theme="calm"` on
    `<html>`);
  - `app.js` keeps today's features. It reads the lens from
    `window.LifeInboxLens` and sends `lifeinbox:changed` after every change.
  - Keep every v1 element ID on the page (a test checks this).
  - Switch views with `LifeInboxShell.goTo()`, never by assigning
    `location.hash`.
- Canonical API: `/api/items`, `/api/analyze`, `/api/tasks`
- Deprecated adapter: `/api/notes`

Prefer extending this stack. Do not introduce React, Vue, Kubernetes,
microservices, or a vector database without a demonstrated product need.

## Data safety

- Never use a real personal Life Inbox database for development or testing.
- Never commit secrets, API keys, OAuth tokens, generated DBs, or private uploads.
- Schema changes go through Alembic migrations.
- Distinguishing original source text, extracted text, AI-inferred content, and
  user-confirmed information is required as those features appear.
- External actions require explicit user confirmation.

## Git

- Milestone branches: `milestone/1-polished-core`, `milestone/2-...`, etc.
- Annotated tags: `milestone-1`, `milestone-2`, ...
- No force-push; no destructive history rewrites.
- Fix regressions on the newest cumulative milestone branch and add a test.

## Definition of done (per milestone)

1. Full pytest suite green
2. Migrations from empty DB succeed
3. App starts against a temp DB
4. Primary API + browser flows exercised
5. Docs updated (`docs/*`, this file)
6. No secrets in the diff
7. Milestone report written with exact run commands
