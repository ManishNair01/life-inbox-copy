# Architecture

## Stack

- **API:** FastAPI
- **ORM:** SQLAlchemy
- **Migrations:** Alembic (authoritative schema owner)
- **DB:** SQLite locally (temp/test DBs for development)
- **UI:** HTML + vanilla JS/CSS
- **AI:** NVIDIA NIM (`https://integrate.api.nvidia.com/v1`); deterministic fallback organizer always available
- **Voice / Speech:** Browser MediaRecorder + ffmpeg 16kHz WAV conversion + NVIDIA NIM ASR (`openai/whisper-large-v3`) + transcript cleanup by the configured LLM (`NVIDIA_LLM_MODEL`)

## Core modules

| Module | Responsibility |
| --- | --- |
| `app/main.py` | HTTP routes, error shaping, startup health checks |
| `app/database.py` | Models, persistence helpers, fingerprints, task upsert |
| `app/schemas.py` | Request/response and analysis contracts |
| `app/llm.py` | The one path for every AI call: client, model, timeout, size limits, retry, `ai_calls` log; and the user's AI switch (change 025: `allowed()`, fails closed) |
| `app/review.py` | The weekly review (one call per user per week), topic proposals from note groups, area summaries (rewritten only when the area changes) and Captain's daily greeting (change 020) |
| `app/scout.py` | Scout, the catch-up helper (change 018): its questions, answers, bulk actions and weekly push, worked out by code |
| `app/sensitive.py` | Secrets in notes (change 016): `looks_secret`, `mask_secrets`; a secret is masked on screen, never sent to the AI, never memory |
| `app/bots.py` | The five life areas, their 3 default topics each, "about" text for the AI, offline keyword rules |
| `app/organizer.py` | Organization prompts (through `app/llm.py`) + offline fallback |
| `app/capture/` | Rich capture (URL, PDF, image, voice note pipeline) |
| `app/retrieval/` | Keyword + local TF-IDF search; Ask me v2 (change 019): notes, remembered facts and the tasks for the days asked about, every citation checked, "How I answered" |
| `app/attention/` | Timing parse, attention buckets, briefing helpers; `glance.py`: the Dashboard's numbers and "Captain noticed", worked out by code |
| `app/integrations/` | Replaceable Calendar adapter (mock / preview-only Google) |
| `app/auth.py` / `app/config.py` | Password login (argon2id), server-side sessions (`auth_sessions`), startup config validation |
| `app/storage_backend.py` | Upload storage abstraction (local FS default) |
| `app/templates` / `app/static` | Browser UI: the three-pane app (see below) |

## Browser app (change 009)

- **The page** (`app/templates/index.html`) is three panes:
  - left: features, then pinned topics;
  - centre: the composer, then the chosen view;
  - right: Captain and the five life areas.
  Each pane scrolls on its own. Below 900 px they stack.
- **`app/static/shell.js`:**
  - routes: `#/home`, `#/topics`, `#/topic/<id>` (a topic's page, change 010),
    `#/timeline`, `#/calendar`, `#/priority`, `#/dashboard`, `#/ask`,
    `#/search?q=`, `#/settings`;
  - the lens: `?bot=`, one area, kept in the address;
  - draws Home, an area's page, Topics and spaces (cards by area, packed into
    columns), the topic page (filters, rename, move, delete), Timeline (week and
    month), the Calendar's day pop-up, Priority (columns, drag to change, saved
    as your value), the Dashboard (`GET /api/dashboard/glance`), search and the
    note page;
  - shows calendar previews in a dock.
  - **It switches views with `pushState`, never by assigning `location.hash`.**
    `app.js` reloads its lists on `popstate`, and a hash assignment fires
    `popstate`.
- **`app/static/shell_logic.js`** is the pure logic: routes, week, Next up,
  Today's focus, pinned topics, topic groups and kind filters, breadcrumb and
  summary text. It's a plain
  script in the browser and a module in Node tests.
- **`app/static/app.js`** keeps v1's features inside the views, with every v1
  element ID:
  - it reads the lens from `window.LifeInboxLens` and adds `?bot=` to its
    lists;
  - after every successful change it sends `lifeinbox:changed`, and the shell
    refreshes the panels.
- **`app/static/shell.css`:** the layout, and the calm theme as
  `html[data-theme="calm"]` overrides of the `--li-*` variables. Its overrides
  of v1 components use `:where()`, so they never beat the shell's own rules.

## Data model (current)

- `inbox_items` — canonical captures
- `notes` — legacy safety copy (not authoritative)
- `topics` — user-editable spaces/projects: 15 seeded defaults across the five
  life areas, plus the v1 catch-all until change 014; `bot_key` (area) and
  `origin` (built_in, user, ai); one level of subtopics via `parent_topic_id`.
  Names are unique per user (any case); a rename also renames the notes'
  `item_insights.category` and saved analysis buckets (change 010)
- `analysis_runs` — analyze attempts + JSON result (includes inbox fingerprint)
- `item_insights` — AI category/title/priority/tags/rationale/topic plus user overrides
- `item_relations` — duplicate / near-duplicate / related pairs (dismissible)
- `tasks` / `task_source_items` — durable tasks; multiple tasks per source allowed;
  AI vs confirmed timing distinguished, with normalized optional local due time.
  `priority` is the AI's; `user_priority` is yours (a Priority view drag) and,
  when set, is the task's priority everywhere; `completed_at` records when it was
  done (change 011, migration 0019). A confirmed date (`timing_confirmed`) only
  moves when you change it (`POST /api/tasks/{id}/date`) or edit its note: an
  edit sets `date_recheck`, and the next analysis moves the date if the new
  text disagrees, unconfirmed, so you are asked again (change 012).
  `due_confidence` records where a date came from (migration 0021):
  `from_note` when the note's words name the day (on `due_on`), `suggested`
  for a guess (in `suggested_due_on` / `suggested_due_time`, off the calendar
  and reminders until confirmed), `user_confirmed` once you pick or confirm
  it. Dates are read relative to the day the note was written or last
  edited, in `LIFE_INBOX_TIMEZONE`
- `task_date_changes` — the history of task dates (set, postponed, moved
  earlier, confirmed, moved by an edit), kept per note and shown as its
  "Updates" (`GET /api/items/{id}/updates`); survives a task being replaced
- `inbox_items.link_card` (change 015, migration 0024): what code read from a
  saved link (kind, title, site or channel, structured facts, up to 1,500
  characters of text); the filing call's source for a link, not AI output
- `item_insights` filing columns (change 014, migration 0023): the rule that
  decided (R1-R6), confidence, the two choices when unsure, who filed it (AI,
  offline, you), `filing_pending` (no topic until you pick), and AI output
  kept apart: a source's summary and next step, a voice note's tidied
  transcript
- `captain_answers` — your answer to each of Captain's "Needs you" cards
  (Not now, a pick, Drop it, a note for a failed capture...), one row per
  card key so an answered card doesn't come back (change 013, migration
  0022); change 016 turns them into memory examples
- `memory_facts` (change 016, migration 0027) — what Life Inbox learned about
  you: long-term facts, short-term plans (with `valid_until`) and examples of
  how you file. Each has its area, source notes, where it came from (your
  words, a correction, a Captain answer…) and a status: suggested (from your
  words, until seen twice or confirmed), confirmed, expired, or deleted (text
  erased; the row stays so the fact is never suggested again). One row per
  normalized text per user. Health facts only with
  `user_settings.health_memory_consent`; never a secret
- `topic_proposals`, `bot_summaries`, `greetings` (change 020, migration 0029)
  — topics the weekly review suggests (pending, created, declined, never; a
  group's `area:word` signature so "Don't suggest this" sticks), each area's
  saved summary with a key of what it held, and Captain's greeting per day.
  `topics.proposed_by` / `evidence_item_ids` / `approved_at` keep a proposed
  topic's history
- `task_events` (change 018, migration 0028) — what happened to a task (done,
  rescheduled, dropped with an optional reason, someday, kept, reopened), by
  you or Scout, with the day it was on and moved to. `tasks.someday` /
  `someday_since`: a task for some day, with no date. `user_settings.away_days`:
  how long you were away, until the catch-up is done
- `user_settings` — one row per user: health-memory consent (off), the AI
  switch (025), the weekly catch-up day and time (018), last seen / catch-up /
  review, onboarding done. `GET/PATCH /api/settings`
- `item_insights.memory_used` (change 017) — the hints from memory the filing
  call said it used (id and text), shown in the note's "Why it's here"
- `plan_updates` (change 017) — a note that seems to move one of your plans:
  the plan's task, the note's version of it and the new day; waiting until you
  answer Captain's "Did a plan move?" (Yes moves the task and links the note;
  "a different one" makes the note's own task)
- `ai_calls` — one row per AI request: user, action, model, outcome, sizes,
  duration and provider status code; never prompt or answer text
  AI vs confirmed timing distinguished, with normalized optional local due time
- `notification_preferences`, `push_subscriptions`, and
  `notification_deliveries` — per-user Web Push opt-in, browser subscriptions,
  and idempotent delivery/retry history

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

## Retrieval + Ask My Inbox

- `GET /api/search?q=` — ranked passages with keyword and semantic scores
- `POST /api/ask` — extractive grounded answers with per-item citations
- Insufficient evidence returns an explicit “not enough information” response (no fabrication)
- Semantic layer is local TF-IDF cosine similarity (no vector database, no paid API in tests)

## Attention & safe actions

- Timing phrases stay on tasks (`timing_text` / `ai_timing_text`); normalized
  `due_on` + `due_confidence` power Today/Upcoming/Overdue/Unscheduled views.
- A guessed date ("this weekend", "by Friday") is only a suggestion
  (`suggested_due_on`) until the user confirms it: it is not on `due_on`, so
  it is off the calendar, the daily digest and the one-hour alert. A day the
  note's words name is used straight away (change 012).
- Snooze / reminder fields are local only (`snoozed_until`, `reminder_at`).
- Opted-in browser push sends one daily digest for open tasks due on the user's
  local date. AI-linked High-priority tasks with an explicit, unambiguous time
  also receive a push one hour before. Date-only tasks are never assigned a
  guessed time. Undated tasks are not scheduled; users may opt into a simple
  count prompt in the digest.
- `python -m app.notifications.dispatcher` is the one-shot scheduler entry
  point and must run once per minute in deployments. The Compose
  `notifications` service provides a local minute-loop worker. Push requires
  HTTPS, browser permission, and VAPID keys.
- Calendar integrations: `GET /api/calendar/status`, `POST /api/calendar/preview`,
  `POST /api/calendar/confirm`. Mock confirm stores a local receipt.
  Google provider is preview-only; confirm is blocked (no OAuth / no writes).

## In-App Calendar

- **Single Source of Truth**: The existing `tasks` table (`TaskRecord`) stores canonical date metadata (`due_on`, `due_confidence`, `timing_text`, `timing_confirmed`). Joined with `task_source_items` and `inbox_items` to retrieve full provenance without a separate event table or migrations.
- **Endpoint**: `GET /api/calendar/events?start=YYYY-MM-DD&end=YYYY-MM-DD` provides read-only, performant queries filtered by date range and user isolation (`require_owner_id()`). Zero LLM / external API calls on page load.
- **Date Normalization**: `app/attention/dates.py:parse_timing_phrase` parses ISO dates, Month-Day ("Nov 3"), Day-Month ("3 Nov"), Month-only ("sometime in March"), relative expressions ("next Friday", "tomorrow"), and explicit time strings.
- **Lifecycle Rules**:
  - Notes without dates are completely excluded.
  - Only real dates are listed: a day the note named or one you set. A guessed
    date joins once you confirm it (change 012), so `needs_confirmation` is
    never true for a listed event; it stays for compatibility.
  - Completed tasks are displayed struck through with completion indicators.
  - Dismissed tasks are excluded from the calendar.
  - Deleting a source note cascades to orphan tasks and immediately removes calendar entries.
- **Frontend & Interactions**: Vanilla JS month grid with ARIA accessibility, keyboard navigation, event indicators, day inspector with source badges (`text`, `voice`, `url`, `pdf`, `image`), and smooth-scroll/pulse highlighting to source notes. Automatically refreshes on note creation, edit, deletion, or analysis.

## External services

Automated tests fake the AI client (everything goes through `app/llm.py`) and
must not call paid APIs. Live calls are for
explicit manual smoke testing only. Never enable real Calendar OAuth/writes
without owner approval.
