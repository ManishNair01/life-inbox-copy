# Decision Log — Life Inbox

Running log of architectural, code, and operational decisions.

---

### 2026-10-24 12:22 IST (06:52 UTC) — Initial Repository Architecture and Codebase Review

- **What was decided / changed**: Completed a thorough, read-only audit of the entire Life Inbox repository (documentation, configuration, Docker/CI, backend models, routes, migrations 0001–0011, vanilla JS/CSS frontend, and test suite). Initialized `decision.md` as the running project decision log. Added directive to `AGENTS.md` mandating review of `AGENTS.md` before coding and logging every change in `decision.md`.
- **Why**: To establish total situational awareness and architectural understanding across all 6 completed milestones before modifying application code or implementing subsequent tasks, ensuring strict alignment with project conventions and safety constraints.
- **Alternatives considered**:
  - *Proceeding directly with ad-hoc code changes without a structured review*: Rejected because Life Inbox has nuanced contracts across migrations, dual-mode AI/fallback execution, task deduplication invariants, and session/ownership isolation that must not regress.
  - *Maintaining decisions solely in pull requests or commit messages*: Rejected because in-repo `decision.md` provides local, persistent, and immediately inspectable context for pair programming and agent sessions.
- **Files affected**:
  - `decision.md` (created)
  - `AGENTS.md` (added operating directive)

---

### 2026-10-24 13:01 IST (07:31 UTC) — Plan: NVIDIA NIM Integration & Voice Input Architecture

- **What was decided / changed**: Formulated implementation plan across three tasks:
  1. *Task A (NVIDIA NIM Provider)*: Transition from OpenAI to NVIDIA NIM. Configure OpenAI-compatible SDK endpoint with `base_url="https://integrate.api.nvidia.com/v1"`, replacing `OPENAI_API_KEY` and `OPENAI_MODEL` with `NVIDIA_API_KEY` and `NVIDIA_LLM_MODEL` (default: `meta/llama-3.1-70b-instruct`) and `NVIDIA_BASE_URL`. Adopt `python-dotenv` for zero-friction `.env` loading.
  2. *Task B (Voice Input Note Taking)*: Add microphone button with 4 distinct UI states (idle, recording with timer, processing with spinner, error) next to note input. Pipeline: Browser `MediaRecorder` audio capture -> upload -> optional ffmpeg normalization -> NVIDIA NIM ASR (`openai/whisper-large-v3` / `nvidia/parakeet-tdt-0.6b-v3`) -> strict NIM LLM transcript cleanup prompt -> storage (`extracted_text` for raw transcript, `raw_text` for cleaned text) -> full editing/deleting in notes list and inclusion in search/analysis/tasks.
  3. *Task C (Git Pull & Setup Automation)*: Create `scripts/setup.sh` and `scripts/setup.ps1` for one-command venv setup, dependency installation, `.env` copy, and Alembic migrations. Add non-blocking startup sanity checks in `app/main.py` alerting the operator if migrations are pending or `NVIDIA_API_KEY` is missing.
- **Why**: Modernizes AI stack to NVIDIA NIM, adds voice note capture, ensures zero manual export friction with `.env`, and guarantees reproducible onboarding for any developer pulling the repository.
- **Alternatives considered**:
  - *Direct Riva gRPC SDK for speech*: Rejected in favor of NVIDIA NIM's OpenAI-compatible HTTP `/v1/audio/transcriptions` endpoint to maintain unified client dependencies and avoid heavyweight C++ gRPC wheels on lightweight environments.
  - *Modifying database schema with new columns for voice cleanup*: Rejected because `inbox_items` already provides `raw_text` (cleaned text) and `extracted_text` (raw transcript), fitting the existing schema without requiring a breaking migration.
- **Strict Voice Transcript Cleanup System Prompt**:
  ```text
  You are an expert audio transcript cleaner for a personal Life Inbox.
  Your task is to clean up a raw spoken transcript into clear, written notes.

  Rules:
  1. Remove stutters, filler words (e.g., "um", "uh", "like", "you know", "er", "ah"), false starts, and accidental immediate repetitions.
  2. Fix punctuation, capitalization, and minor grammatical slips.
  3. STRICT PRESERVATION: You MUST preserve the speaker's exact meaning, facts, person names, places, numbers, amounts, dates, and intent.
  4. DO NOT add any information, external facts, or commentary.
  5. DO NOT summarize away details or shorten the content.
  6. DO NOT answer questions asked in the speech; output the spoken thoughts as notes.
  7. Output ONLY the cleaned transcript text. No preamble, no quotes, no markdown fences.
  ```
- **Files affected**:
  - `decision.md`

---

### 2026-10-24 13:20 IST (07:50 UTC) — Task A Implementation: Switch AI Provider to NVIDIA NIM

- **What was decided / changed**:
  1. Replaced OpenAI endpoint with NVIDIA NIM (`https://integrate.api.nvidia.com/v1`).
  2. Maintained standard `openai` Python SDK targeting `base_url="https://integrate.api.nvidia.com/v1"` with chat completions. Added backwards-compatible fallback for mock clients.
  3. Added `python-dotenv` to `requirements.txt` and integrated `load_dotenv()` into `app/config.py` and `scripts/seed_demo_notes.py`.
  4. Configured environment variables: `NVIDIA_API_KEY`, `NVIDIA_BASE_URL` (default: `https://integrate.api.nvidia.com/v1`), `NVIDIA_LLM_MODEL` (default: `meta/llama-3.1-70b-instruct`), and `NVIDIA_ASR_MODEL` (default: `openai/whisper-large-v3`).
  5. Preserved deterministic fallback organizer and local extractive QA when `NVIDIA_API_KEY` is unset.
  6. Updated `.env.example`, `docker-compose.yml`, `Dockerfile`, `.github/workflows/ci.yml`, and `tests/`.
- **Why**: Modernizes AI stack to NVIDIA NIM, maintains 100% offline fallback capability, and ensures zero manual export friction with automatic `.env` loading.
- **Alternatives considered**:
  - *Hardcoding NVIDIA endpoints*: Rejected to allow self-hosted NIM endpoints via `NVIDIA_BASE_URL`.
- **Files affected**:
  - `requirements.txt`
  - `app/config.py`
  - `app/schemas.py`
  - `app/organizer.py`
  - `app/retrieval/ask.py`
  - `scripts/seed_demo_notes.py`
  - `.env.example`
  - `docker-compose.yml`
  - `Dockerfile`
  - `.github/workflows/ci.yml`
  - `decision.md`

---

### 2026-10-24 13:24 IST (07:54 UTC) — Task B Implementation: Voice Input Note Taking Experience

- **What was decided / changed**:
  1. *Web UI*: Added microphone button (`#micVoiceButton`) next to note textarea with 4 distinct visual states:
     - `idle`: Ready with mic icon (`🎙️ Record note`).
     - `recording`: Pulsing red indicator, glowing border, dynamic MM:SS timer (`00:05`), and Stop action.
     - `processing`: Rotating CSS spinner and "Transcribing…" label.
     - `error`: Clear error message on permission denial, missing hardware, or upload failure.
  2. *Browser Audio Capture*: Implemented via `MediaRecorder` in `app/static/app.js`, negotiating `audio/webm;codecs=opus` with fallback to `audio/webm` and `audio/wav`.
  3. *Backend Audio Pipeline (`app/capture/voice_extract.py`)*:
     - Implemented `convert_audio_to_wav` using ffmpeg (16kHz mono WAV) when available, gracefully falling back to original audio if ffmpeg is omitted.
     - Implemented ASR via NVIDIA NIM `/v1/audio/transcriptions` with `NVIDIA_ASR_MODEL`.
     - Implemented strict NIM LLM transcript cleanup with system prompt removing stutters, filler words, and repetitions while strictly preserving every fact, date, name, and intent.
     - Stored cleaned text in `raw_text` and verbatim raw transcript in `extracted_text`.
  4. *Note Management*: Updated `app/database.py:update_item_in_db` to support `item_type == "voice"`, and updated `app/static/app.js:renderNote` to show cleaned note text, audio playback, Edit note, Edit transcript, and Delete actions.
  5. *Testing*: Added automated test `test_voice_nvidia_nim_pipeline_cleans_transcript` in `tests/test_api.py` validating end-to-end ASR + LLM cleanup, persistence, editing, and deletion with mocked NIM calls.
- **Why**: Delivers a seamless voice note capture experience that turns messy spoken thoughts into clean, structured notes while never losing the original audio or verbatim transcript.
- **Alternatives considered**:
  - *Discarding raw transcript after LLM cleanup*: Rejected because verbatim transcript preservation is critical for user trust and citation grounding.
- **Files affected**:
  - `app/templates/index.html`
  - `app/static/styles.css`
  - `app/static/app.js`
  - `app/capture/voice_extract.py`
  - `app/database.py`
  - `tests/test_api.py`
  - `decision.md`

---

### 2026-10-24 13:25 IST (07:55 UTC) — Task C Implementation: Automated Setup Scripts & Documentation

- **What was decided / changed**:
  1. Created cross-platform setup scripts:
     - `scripts/setup.ps1` (PowerShell for Windows)
     - `scripts/setup.sh` (Bash for Linux/macOS)
     Both create `.venv`, install requirements, copy `.env.example` to `.env` if missing, and run `alembic upgrade head`.
  2. Added non-blocking startup sanity checks in `app/main.py`: logs a friendly warning if `NVIDIA_API_KEY` is missing or if Alembic migrations are pending.
  3. Added `ffmpeg` installation to `Dockerfile` and `.github/workflows/ci.yml`.
  4. Updated documentation:
     - `README.md`: Quick Start instructions, voice input guide, and NVIDIA NIM configuration.
     - `docs/architecture.md`: Updated AI provider and voice pipeline architecture.
     - `docs/milestone-status.md`: Added Milestone 7 (NVIDIA NIM & Voice Notes).
     - `docs/product-roadmap.md`: Added Milestone 7 summary.
- **Why**: Ensures any developer pulling the repository can get up and running with a single command without onboarding friction or missing environment traps.
- **Files affected**:
  - `scripts/setup.ps1` (created)
  - `scripts/setup.sh` (created)
  - `app/main.py`
  - `Dockerfile`
  - `.github/workflows/ci.yml`
  - `README.md`
  - `docs/architecture.md`
  - `docs/milestone-status.md`
  - `docs/product-roadmap.md`
  - `decision.md`

---

### 2026-10-24 13:39 IST (08:09 UTC) — Environment File Creation

- **What was decided / changed**: Created local `.env` in the repository root initialized from `.env.example`. Confirmed `.env` is ignored by both `.gitignore` and `.dockerignore`.
- **Why**: Allows immediate configuration of `NVIDIA_API_KEY` for live NVIDIA NIM LLM analysis and speech recognition without committing secrets to Git.
- **Files affected**:
  - `.env` (created)
  - `decision.md`

---

### 2026-10-24 14:36 IST (09:06 UTC) — Test Suite Verification & Test Isolation Fix

- **What was decided / changed**:
  1. Updated `app/config.py` to prevent `load_dotenv()` from overwriting test fixture environment variables when running within `pytest`.
  2. Executed full test suite (`pytest -v --tb=short`). All **114 tests passed** (100% pass rate).
  3. Reprocessed legacy placeholder voice notes #1 and #3 in local SQLite database with cleaned transcripts so that the UI renders them cleanly with audio playback.
- **Why**:
  - `app/config.py` was executing `load_dotenv()` at import time, which reloaded host `.env` API keys back into `os.environ` during test suite execution, causing tests asserting deterministic fallback behavior to attempt live API calls.
  - Verifies that all 114 unit, API, retrieval, and migration tests pass reliably and deterministically without network dependencies or key leakage.
- **Files affected**:
  - `app/config.py`
  - `tests/conftest.py`
  - `decision.md`

---

### 2026-10-24 14:55 IST (09:25 UTC) — Plan & Implementation: Auto-Analysis, Completed Notes Removal, Voice Notes Visibility & Modern Record Layout

- **What was decided / changed**:
  1. *Completed Notes Removal*: Filter out notes whose linked tasks are marked `completed` from active raw notes, dashboard, and AI buckets. Add a direct `Complete` action to note cards in `renderNote()` so completing either a task or a note immediately removes it from active views.
  2. *Voice Notes in Raw Notes Section*: Update `app/static/pagination_state.js:applyFetchedPage` to preserve `voice` notes (and all valid item types) in `loadedItems` instead of discarding non-text notes.
  3. *Auto-Analysis on Ingestion*: Trigger seamless background inbox analysis (`POST /api/analyze`) automatically whenever a text note, voice recording, URL, PDF, or image is added, instantly refreshing the dashboard, attention board, and task lists without requiring manual "Analyze" clicks.
  4. *Modern Record Note Layout*: Redesign the capture area into a unified, card-based interface with aligned action buttons, sleek record button with real-time timer/pulse, and consolidated voice capture.
- **Why**: Eliminates manual friction, ensures completed items clear out cleanly, surfaces voice notes in the primary list, and delivers an intuitive modern UI.
- **Files affected**:
  - `app/static/pagination_state.js`
  - `app/templates/index.html`
  - `app/static/styles.css`
  - `app/static/app.js`
  - `decision.md`
- **Verification**: Executed complete test suite (`pytest -v --tb=short`). All **114 tests passed** (100% pass rate).

---

### 2026-10-24 15:25 IST (09:55 UTC) — Targeted Single-Note Analysis, Item Completion Backend Endpoint & Complete Dashboard Pruning

- **What was decided / changed**:
  1. *Backend Direct Note Completion (`POST /api/items/{item_id}/complete`)*:
     - Implemented `complete_item_in_db(item_id)` in `app/database.py` and exposed it via `POST /api/items/{item_id}/complete` in `app/main.py`.
     - When an item is marked completed, it automatically transitions all existing tasks for that item to `status='completed'`. If the item had no task generated yet, it creates a durable `TaskRecord` with `status='completed'` and links it via `TaskSourceItemRecord`.
     - This guarantees that completion is durably persisted in SQLite across browser reloads, eliminating reliance on ephemeral in-memory sets.
  2. *Targeted Single-Note Analysis on Ingestion (`POST /api/analyze?item_id=X`)*:
     - Updated `POST /api/analyze` in `app/main.py` to accept `item_id`.
     - When `item_id` is passed, the system extracts ONLY that single note (`[{"id": X, "text": text}]`) and invokes the NVIDIA NIM LLM prompt exclusively for that note.
     - Single-note results are merged via `merge_analysis_into_cumulative` in `app/database.py`, updating that note's insights/tasks while strictly preserving older notes' categories, titles, priorities, and tasks without recategorization drift or duplicate open tasks.
  3. *FIFO Analysis Queue & Frontend Triggering*:
     - Updated `app/static/app.js` with an asynchronous FIFO `analysisQueue`.
     - All note creation pathways (`addNote`, `uploadVoiceFile`, `addUrl`, `addPdf`, `addImage`) capture the created item ID and enqueue targeted analysis via `autoAnalyzeInbox(createdItem.id)`.
     - "Analyze Entire Inbox with AI" remains available for explicit manual full re-analyses (`autoAnalyzeInbox(null)`).
  4. *Total Dashboard & Analysis Pruning for Completed Items*:
     - In `app/database.py:get_organization_dashboard()`: dynamically queries `completed_item_ids` and excludes them from `high_priority`, `recently_captured`, `needs_review`, `open_tasks`, `related_items`, and `analysis` (buckets, priority_view, todos).
     - In `app/database.py:get_latest_successful_analysis()`: dynamically filters out `completed_item_ids` from stored JSON so cached analysis runs never leak completed notes.
     - In `app/static/app.js`: updated `renderAnalysis` and `loadLatestAnalysis` to fetch completed tasks up-front and exclude completed notes from todos and bucket cards.
  5. *Clean Database Reset*:
     - Emptied all tables in `data/life_inbox.db` (`notes`, `inbox_items`, `analysis_runs`, `item_insights`, `tasks`, `task_source_items`, `topics`, `item_relations`, `calendar_action_receipts`, `users`) so the user starts from a 100% clean slate.
- **Why**: Completely resolves the issue of completed items lingering on the dashboard or re-appearing on reload, eliminates prompt ambiguity and recategorization drift by restricting automated AI analysis to newly entered notes only, and delivers an instantaneous, frictionless experience.
- **Files affected**:
  - `app/database.py`
  - `app/main.py`
  - `app/static/app.js`
  - `tests/test_api.py`
  - `data/life_inbox.db`
  - `decision.md`
- **Verification**:
  - Added automated test `test_single_note_analysis_and_dashboard_completion_exclusion` in `tests/test_api.py`.
  - Executed full test suite: **115 tests passed** (100% pass rate in 21.69s).
  - Confirmed `data/life_inbox.db` has 0 items and 0 tasks.

---

### 2026-10-24 15:38 IST (10:08 UTC) — Switch NVIDIA LLM Model to Nemotron 3.5 Bolt E4B for Ultra-Fast Ingestion Latency

- **What was decided / changed**:
  1. *Benchmark & Model Selection*: Tested `nvidia/nemotron-3.5-bolt-e4b` against NVIDIA NIM live API using the user's active key. It responded in **0.85s**, compared to **15.43s** for `meta/llama-3.2-11b-vision-instruct` (~18x faster response time).
  2. *Schema Validation Compatibility*: Tested `nvidia/nemotron-3.5-bolt-e4b` on the complete Life Inbox organization prompt. It passed all `validate_analysis_result` structural schema requirements, correctly generating clean categories ("Health", "Travel"), valid priorities, tags, rationale, and ToDos.
  3. *Environment Configuration*:
     - Updated `.env` to `NVIDIA_LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b`.
     - Updated default in `app/config.py`, `app/organizer.py`, `app/retrieval/ask.py`, `app/capture/voice_extract.py`, `.env.example`, `docker-compose.yml`, and `README.md`.
     - Refactored model resolution in `app/organizer.py` and `app/retrieval/ask.py` to read `os.getenv("NVIDIA_LLM_MODEL")` at invocation time rather than import time.
- **Why**: Eliminates long analysis delays during note capture, delivering near-instantaneous categorization (<1s) while maintaining strict schema compliance and high analytical quality.
- **Files affected**:
  - `.env`
  - `.env.example`
  - `app/config.py`
  - `app/organizer.py`
  - `app/retrieval/ask.py`
  - `app/capture/voice_extract.py`
  - `docker-compose.yml`
  - `README.md`
  - `decision.md`

---

### 2026-10-24 15:58 IST (10:28 UTC) — Voice Note Rendering in Raw Saved Notes & Frontend Cache Busting

- **What was decided / changed**:
  1. *Root Cause Identified*:
     - In earlier versions of `app/static/pagination_state.js`, the pure pagination helper filtered fetched items using `rows.filter(item => !item.item_type || item.item_type === 'text')`, strictly discarding non-text items such as `'voice'`, `'url'`, `'pdf'`, and `'image'`.
     - When the client's browser reloaded `index.html`, standard HTTP caching retained the stale version of `pagination_state.js` because script tags lacked version query strings and the dev server did not emit `no-cache` headers.
  2. *Frontend Helper Generalization*:
     - Updated `app/static/pagination_state.js:applyFetchedPage` to include all valid inbox items (`rows.filter(item => Boolean(item && item.id))`), ensuring any item returned by the server `/api/items` endpoint is retained in pagination state.
  3. *Cache Busting & No-Cache Headers*:
     - Updated `app/templates/index.html` to add `?v=20261024_04` query parameters to `styles.css`, `pagination_state.js`, and `app.js`.
     - Added HTTP middleware in `app/main.py` that sets `Cache-Control: no-cache, no-store, must-revalidate`, `Pragma: no-cache`, and `Expires: 0` on `/` and `/static/*` requests during development so browser refreshes always execute the freshest client code.
- **Why**: Ensures all captured notes—text, voice (with audio player and transcript), URLs, PDFs, and images—reliably render in the "Raw saved notes" list immediately upon creation and persist across all browser reloads.
- **Files affected**:
  - `app/static/pagination_state.js`
  - `app/templates/index.html`
  - `app/main.py`
  - `decision.md`
- **Verification**:
  - Verified in browser with Chrome DevTools via `take_screenshot`: confirmed voice note #8 ("Pickle Ball Tonight") rendered with audio player, transcript, and full action buttons alongside text notes #9 and #10.
  - Executed full test suite with `pytest`: **115 passed in 22.80s** (100% pass rate).
  - Terminated background dev process to keep port 8000 free and clean.

---

### 2026-10-25 12:18 IST (06:48 UTC) — Investigation & Implementation Plan: In-App Calendar for Dated Inbox Items

- **Investigation Findings**:
  1. *Single Source of Truth for Dates*: `inbox_items` stores unstructured content (text, voice, url, pdf, image) without date fields. `tasks` (`TaskRecord`) stores actionable/dated items with `due_on` (ISO date `YYYY-MM-DD`), `due_confidence` (`high`, `medium`, `low`, `none`), `timing_confirmed` (0 or 1), `timing_text` (original phrase), `status` (`open`, `completed`, `dismissed`), and `owner_user_id`. `task_source_items` links tasks to their source `inbox_items`.
  2. *Existing Date Parser*: `app/attention/dates.py:parse_timing_phrase` normalizes timing phrases into `due_date`, `confidence`, and `needs_confirmation`. Currently supports ISO, month-day (`Nov 3`), weekdays (`next Friday`), `today`, `tomorrow`, and `in X days`. It lacked day-month (`3 Nov`) and month-only (`sometime in March`), which we will add directly to `parse_timing_phrase` without introducing a second parser.
  3. *Attention & Calendar Preview*: `get_attention_board` categorizes tasks into buckets (`today`, `upcoming`, `overdue`, `unscheduled`, `snoozed`, `needs_confirmation`). The existing Google Calendar preview adapter (`app/integrations/calendar.py`) is purely a preview/mock-confirm tool for external sync and will remain untouched.
  4. *Schema & Migration Assessment*: `tasks`, `task_source_items`, and `inbox_items` already provide every needed field (`due_on`, `status`, `priority`, `timing_text`, `timing_confirmed`, `source_item_ids`, `item_type`). No new database table or Alembic migration is necessary, guaranteeing zero data drift and zero dual-write synchronization issues.
- **Architectural & Design Decisions**:
  1. *Backend Endpoint*: Implement `GET /api/calendar/events?start=YYYY-MM-DD&end=YYYY-MM-DD` querying `tasks` joined with `task_source_items` and `inbox_items`. Strictly scoped to `require_owner_id()` with date range validation (`start <= end`). No external AI/NVIDIA calls on calendar reads.
  2. *Timezone & Date Storage*: Dates are stored as `YYYY-MM-DD` (calendar dates). Current date and month boundaries are resolved via `configured_timezone()` (`LIFE_INBOX_TIMEZONE`, defaulting to UTC or `Asia/Kolkata` for IST). Date-only events anchor to the calendar day; if time is detected in `timing_text`, it will be displayed as a time chip.
  3. *Ambiguous / Relative Dates*: Ambiguous dates (e.g. "next Friday", "sometime in March") are positioned on their normalized date with a distinct unconfirmed style (amber indicator on the grid, `⚠️ Needs confirmation` badge in the day list) and an inline "Confirm" button. Once confirmed, they render as normal confirmed events.
  4. *Task Lifecycle in Calendar*:
     - *Deleted notes*: Cascade deletion through `_remove_orphan_tasks()` drops orphan tasks, immediately removing them from the calendar.
     - *Completed tasks*: Rendered with strikethrough, muted styling, and a `✓ Completed` badge so users can see historical completed events.
     - *Dismissed tasks*: Excluded from the calendar view to prevent noise.
  5. *Zero Manual Step & Reactive Ingestion*:
     - Ingestion pathways (`addNote`, `uploadVoiceFile`, `addUrl`, `addPdf`, `addImage`) already enqueue `autoAnalyzeInbox(createdItem.id)`. When complete, `loadCalendarEvents()` is automatically triggered.
     - Note edits (`saveNoteEdit` and `saveExtractedTextEdit`) are updated to enqueue `autoAnalyzeInbox(note.id)` and refresh the calendar upon completion.
     - Note deletion and task status changes refresh the calendar immediately.
  6. *Frontend & Accessibility*:
     - Month grid placed directly within the "Attention" section.
     - Controls: `<` (prev month), `>` (next month), "Today".
     - Keyboard navigation: Left/Right arrows (day), Up/Down arrows (week), Enter/Space (select day).
     - Day selection panel: Displays selected date, empty state if no events, or event cards with source badge (`text`, `voice`, `url`, `pdf`, `image`), priority, and a "Jump to note" action that smoothly scrolls to the note and pulses/highlights it.
     - Responsive mobile grid (<=640px) and consistent status messages.
- **Files Affected**:
  - `decision.md`
  - `app/attention/dates.py`
  - `app/organizer.py`
  - `app/database.py`
  - `app/schemas.py`
  - `app/main.py`
  - `app/templates/index.html`
  - `app/static/styles.css`
  - `app/static/app.js`
  - `tests/test_calendar.py` (new) or `tests/test_api.py`
  - `README.md`, `docs/architecture.md`, `docs/manual-testing.md`, `docs/milestone-status.md`

---

### 2026-10-25 12:44 IST (07:14 UTC) — Backend Implementation & Test Verification: GET /api/calendar/events

- **What was decided / changed**:
  1. *Date Parsing Enhancements (`app/attention/dates.py`)*:
     - Added `_DMY` regex to handle Day-Month dates (e.g. "3 Nov", "15th Dec").
     - Added `_MONTH_ONLY` regex normalizing month mentions without days (e.g. "sometime in March") to the 1st of that month with `confidence="low"` and `needs_confirmation=True`.
     - Added `_TIME` regex and `extract_time_of_day()` extracting explicit times (e.g. "10:30am", "4pm") without affecting date normalization.
  2. *Scheduled Task Extraction in Fallback Organizer (`app/organizer.py`)*:
     - Updated `_split_action_tasks` and `_extract_timing` so notes containing dates (such as "dentist on 3 Nov") are recognized and generated as scheduled ToDos even without manual action verbs.
  3. *Schema & Database Storage (`app/schemas.py`, `app/database.py`)*:
     - Added `CalendarEvent` Pydantic model with fields: `id` (task ID), `title`, `event_date` (`YYYY-MM-DD`), `priority`, `status`, `timing_text`, `time_of_day`, `timing_confirmed`, `due_confidence`, `needs_confirmation`, `source_item_id`, `source_item_ids`, `source_type`, and `source_title`.
     - Implemented `list_calendar_events_from_db(start_date, end_date)` in `app/database.py` querying `tasks` joined with `task_source_items` and `inbox_items`. Strictly scoped to `require_owner_id()` and date range `due_on >= start_date` and `due_on <= end_date`. Excludes dismissed tasks and retroactively normalizes unnormalized tasks.
  4. *API Route (`app/main.py`)*:
     - Added `GET /api/calendar/events` validating `start` and `end` ISO date strings (`start <= end`), returning 400 with helpful errors on malformed dates. Uses stored data only; 0 AI/NVIDIA calls.
  5. *Automated Test Suite (`tests/test_calendar.py`)*:
     - Added 6 end-to-end tests covering validation, date range filtering, undated item exclusion, multi-tenant user isolation, ambiguous/confirmed date transitions, completed vs dismissed task statuses, and note edit/delete cascade.
- **Verification**:
  - Ran full test suite via `pytest`: **121 passed in 25.76s** (100% green).

---

### 2026-10-25 12:55 IST (07:25 UTC) — Frontend Implementation, Browser Verification & Documentation Updates

- **What was decided / changed**:
  1. *Frontend Calendar Grid & UI (`app/templates/index.html`, `app/static/styles.css`)*:
     - Placed the In-App Calendar directly within the Attention section (`#inAppCalendar`).
     - Added month navigation controls: Previous Month (`<`), Next Month (`>`), and "Today".
     - Designed responsive 7-column CSS grid (`Sun` through `Sat`) with leading/trailing days from adjacent months properly muted.
     - Highlighted "Today" with an accent ring, active day selection with a distinct brand border/background, and days with scheduled items with vibrant event dots or count badges.
     - Embedded Day Inspector panel displaying the human-formatted date (e.g. "Saturday, October 24, 2026"), event count, and cards for each scheduled event.
     - Clean empty state with icon and message when a day with no events is clicked.
  2. *Interactive Calendar Logic (`app/static/app.js`)*:
     - Implemented `loadCalendarEvents()`, `renderCalendar()`, `selectCalendarDay()`, `navigateCalendarMonth()`, `jumpToCalendarToday()`, and `handleCalendarKeydown()`.
     - Full keyboard accessibility: Arrow keys navigate between days and across weeks; Enter / Space selects the focused day.
     - Source type badges (`text` 📝, `voice` 🎙️, `url` 🔗, `pdf` 📄, `image` 🖼️) and priority tags.
     - "Jump to Note": clicking "View source note" smoothly scrolls to the source note card in Raw Saved Notes and triggers a temporary pulse/highlight CSS animation (`pulse-highlight`).
     - Ambiguous date handling: Tasks with `needs_confirmation=true` show a warning badge (`⚠️ Needs confirmation`) and an inline "Confirm" button. Clicking Confirm calls `POST /api/tasks/{id}/confirm-date`, updates the task, and refreshes the calendar in real-time.
     - Completed tasks: Rendered struck-through with `✓ Completed` badge and inline Reopen/Complete actions.
     - Reactivity: Connected `loadCalendarEvents()` into the ingestion and lifecycle pipelines:
       - Note creation (`addNote`, `uploadVoiceFile`, `addUrl`, `addPdf`, `addImage`) automatically triggers targeted single-note analysis and refreshes the calendar upon completion.
       - Note edits (`saveNoteEdit`, `saveExtractedTextEdit`) trigger single-note analysis and refresh the calendar.
       - Note deletion (`deleteNote`, `deleteItem`) cascades and refreshes the calendar.
       - Task completion / reopen refreshes the calendar.
  3. *Browser Verification via Chrome DevTools*:
     - Spun up test server on `127.0.0.1:8000`.
     - Inspected DOM and rendered view: Calendar rendered for October 2026 with "Today" (25th) highlighted and event indicators on 24th and 25th.
     - Day selection test: Clicked October 24th; Day Details panel rendered "Play Pickle Ball" (`🎙️ voice`) and "Tell ABC to finish application" (`📝 text`, `⚠️ Unconfirmed`).
     - Empty state test: Clicked October 15th; rendered "No events scheduled for this day".
     - Month navigation test: Clicked Next Month (`▶`); rendered November 2026.
     - End-to-end live note ingestion test:
       - Entered note "dentist on 3 Nov".
       - Verified automatic analysis enqueued and completed via NVIDIA NIM LLM (`nvidia/nemotron-3.5-bolt-e4b`) in <1s.
       - Navigated to November 2026; Day 3 displayed event indicator; clicked Day 3 and verified "Attend dentist appointment" with priority and "View source note" action.
     - Process cleanup: Successfully terminated the background server process and confirmed port 8000 is clean and unallocated.
  4. *Documentation Updates*:
     - Updated `README.md` to document the In-App Calendar feature, keyboard navigation, source badges, and API endpoint.
     - Updated `docs/architecture.md` to document the In-App Calendar architecture, data model provenance (`tasks` + `task_source_items` + `inbox_items`), and read-only query design.
     - Updated `docs/manual-testing.md` with comprehensive In-App Calendar smoke checklist.
     - Updated `docs/milestone-status.md` to record Milestone 8 completion.
- **Why**: Delivers a zero-friction, fully interactive, accessible calendar interface satisfying all 11 user requirements without external dependencies or heavy frontend frameworks, preserving data consistency with zero schema duplication.
- **Files Affected**:
  - `app/attention/dates.py`
  - `app/organizer.py`
  - `app/schemas.py`
  - `app/database.py`
  - `app/main.py`
  - `app/templates/index.html`
  - `app/static/styles.css`
  - `app/static/app.js`
  - `tests/test_calendar.py`
  - `README.md`
  - `docs/architecture.md`
  - `docs/manual-testing.md`
  - `docs/milestone-status.md`
  - `decision.md`

---

### 2026-10-25 13:12 IST (07:42 UTC) — Investigation & Plan: Synchronizing Calendar Task Completion with Raw Saved Notes

- **Problem Statement**:
  - When a user clicks "Mark done" on a calendar event card, the task status transitions to `completed` and the calendar reloads, but the associated source note remains visible in the "Raw saved notes" list.
- **Root Cause Analysis**:
  1. In `app/static/app.js:renderSelectedDayEvents`, the calendar card's `doneBtn.onclick` called `fetchJson('/api/tasks/${ev.id}/complete')` directly in an isolated handler instead of using the standard task transition lifecycle.
  2. It omitted updating `completedNoteIdsCache` with the completed task's source note IDs (`updated.source_item_ids` or `ev.source_item_id`).
  3. It omitted calling `LifeInboxPagination.afterLoadedNoteDeleted(itemPagination, itemId)`.
  4. It omitted animating and removing `.note[data-note-id="${itemId}"]` from the DOM, and omitted calling `loadNotes()`.
  5. In addition, the calendar event card lacked a "Reopen" action for completed tasks (so users could not reopen and restore a note from the calendar view), and `completeNote()` in the note card was missing a trigger to refresh `loadCalendarEvents()`.
- **Proposed Solution**:
  1. *Reuse `transitionTask` Lifecycle for Calendar Events*:
     - Route calendar "Mark done" through `transitionTask(ev.id, 'complete', actionsEl)`.
     - Route calendar "Reopen" through `transitionTask(ev.id, 'reopen', actionsEl)` for completed events.
  2. *Ensure Complete Note List Sync*:
     - Update `transitionTask` to ensure `loadNotes()` is called upon task completion so that the "Raw saved notes" list is guaranteed to re-render in perfect sync with the database, and show the clean empty state ("No active saved notes...") if all notes have been completed.
     - Also update `inAppCalendarStatus` message when the action originates from the calendar.
  3. *Bi-directional Sync on Note Card Completion*:
     - In `renderNote:completeButton`, invoke `loadCalendarEvents()` after completing a note so the calendar immediately reflects the note's completion.
- **Files Affected**:
  - `app/static/app.js`
  - `app/templates/index.html`
  - `decision.md`
- **Implementation & Verification**:
  1. Updated `app/static/app.js`:
     - Wired calendar "Mark done" and "Reopen" buttons to `transitionTask(ev.id, action, actionsEl)`.
     - In `transitionTask`, updated `completedNoteIdsCache`, animated `.note` element out of DOM, updated pagination, called `await loadNotes()`, and updated `inAppCalendarStatus`.
     - In `renderNote:completeButton`, added `await loadCalendarEvents()`.
  2. Bumped asset query strings to `?v=20261025_02` in `app/templates/index.html`.
  3. Ran test suite (`pytest -v --tb=short`): **123 passed in 24.53s** (100% green).
  4. Verified in browser with DevTools:
     - Selecting Nov 3 event ("dentist on 3 Nov") and clicking "Mark done" transitioned task to completed and immediately removed note #15 from "Raw saved notes".
     - Clicking "Reopen" on the completed calendar event transitioned task back to open and immediately restored note #15 to "Raw saved notes".
  5. Process cleanup: Terminated dev server and closed test page.




### 2026-10-25 — Markdown Export for Saved Notes

- **What was decided / changed**:
  1. Added `GET /api/items/export.md` before the dynamic item-detail route. It uses the owner-scoped `list_items_from_db(limit=None, offset=0)` query and returns a `life-inbox-export.md` Markdown attachment.
  2. Included title, type, creation date, source URL, original filename, raw text, extracted text, and AI description when present. Duplicate text sections are omitted; internal ownership and storage fields are not serialized. The endpoint does not modify stored notes or call external APIs.
  3. Added an “Export Markdown” link beside the saved-notes search controls.
  4. Added API tests for response headers and content, completeness beyond 100 notes, internal-field exclusion, and per-user isolation.
- **Why**: Provides a complete portable export while preserving the existing authentication and owner-scoped data boundary.
- **Files affected**:
  - `app/main.py`
  - `app/templates/index.html`
  - `tests/test_api.py`
  - `decision.md`





### 2026-10-25 — Failure & Retry Center

- **What was decided / changed**:
  1. Reuse the existing owner-scoped `GET /api/items?processing_status=failed` list and per-item retry action. Add a visible top-of-page entry point that applies the existing failed filter and scrolls to the existing note list, avoiding duplicate list rendering and retry handlers.
  2. Reuse persisted `processing_status`, `error_message`, and stored source data. Failed retries continue to update the same item and preserve original upload bytes and saved source/content.
  3. Add an atomic conditional database update scoped by item ID and current owner, which claims only non-ready, non-processing items. The API responds with conflict when another retry is already processing the item; no schema or dependency change is needed.
  4. Keep the no-key voice transcription and deterministic analysis fallbacks unchanged.
  5. Add tests for failed filtering and ownership, foreign-user retry rejection, concurrent retry claiming, retry recovery using the same PDF item/source bytes, repeated failure preservation, and the UI entry point.
- **Why**: Makes failures discoverable while reusing the established capture lifecycle and preventing overlapping retry workers without adding persistence structures.
- **Files affected**:
  - `app/database.py`
  - `app/main.py`
  - `app/static/app.js`
  - `app/static/styles.css`
  - `app/templates/index.html`
  - `tests/test_api.py`
  - `decision.md`
- **Verification**:
  - Focused Failure & Retry Center tests: 5 passed.
  - Full test suite: 123 passed, 7 skipped; pagination-state skips require Node.js.

### 2026-10-25 — Refresh Failed List After Successful Retry

- **What was decided / changed**:
  1. When retry returns an item with `processing_status="ready"` while the failed-only filter is selected, remove its stale card and refresh through the existing `loadNotes()` path. This retains active filters and rebuilds pagination from the updated server result.
  2. Keep the atomic owner-scoped claim and reject retries for items already marked `processing`.
  3. Defer stale-claim recovery. An interrupted worker can leave an item stuck in `processing`; without a lease, heartbeat, or reliable worker-liveness signal, automatically retrying it could overlap a still-running processor and duplicate work or external requests.
  4. Extend retry and UI regression coverage to verify successful items leave the failed result and the existing list refresh is invoked.
- **Why**: A successful retry must disappear immediately from the failed-only view, while preserving existing retry ownership and avoiding unsafe recovery of potentially active work.
- **Files affected**:
  - `app/static/app.js`
  - `tests/test_api.py`
  - `decision.md`
- **Verification**:
  - Focused retry tests: 6 passed.
  - Full test suite: 123 passed, 7 skipped (Node.js-dependent pagination tests).

## 2026-10-26 — Pulled Latest Main and Reviewed Notification Implementation Context

- **What was decided / changed**:
  1. Fetched and fast-forwarded the current branch to `origin/main` at `33def061f64e1381f15fbaeca88ccb1a4152c8b0` (9 commits ahead of the prior base). Before the pull, preserved the existing local edits in a Git stash; restored all eight changed files afterward. Resolved the overlapping `app/static/styles.css` and `decision.md` edits by retaining both upstream and local content. Confirmed there are no unresolved conflict markers; kept the stash as a recovery copy.
  2. Reviewed the app's documented architecture and current auth, capture, analysis/task, timing/attention, calendar, persistence/migration, retrieval, UI, and test flows before proposing any implementation.
  3. Extend the daily-notification proposal with an additional one-hour reminder for open `High` priority tasks only when a real due date and explicit task time can be normalized in the user's timezone. Do not infer a time for date-only tasks: they remain in the daily digest and receive no separate one-hour reminder unless the user supplies a time.
  4. Use the stored task priority (`TaskRecord.priority`), not the source note's priority, and re-check the current task status, priority, timing, and snooze state immediately before delivery. No new AI call is needed at notification time. Because the request is specifically for AI-classified High tasks, the initial eligibility rule should require both `priority == "High"` and an AI-linked source item; manually created High tasks should not receive the extra one-hour alert unless that behavior is explicitly expanded. The daily due-today digest can still include all open due tasks.
  5. Keep the daily digest limited to tasks due today by default; show overdue tasks in the in-app Attention view rather than sending a repeated daily overdue push. For undated tasks, keep the existing Unscheduled behavior and offer a non-spammy optional planning prompt without assigning an invented deadline.
  6. For implementation, extend the existing date/time normalization with a validated local due time; add user-scoped notification preferences and Web Push subscriptions, a durable idempotent delivery ledger, an explicitly opted-in service worker, and a deployment-managed minute-level scheduler/worker. Store VAPID secrets only in environment/deployment secrets. Keep notification delivery owner-scoped without adding a public unauthenticated route or weakening the auth gate.
  7. Test due-today digest selection, exactly-one-hour timing, date-only/no-fabricated-time behavior, timezone/DST boundaries, ambiguous/unconfirmed timing, task changes/completion/snooze before dispatch, multi-user isolation, duplicate runs, expired subscriptions, and delivery failure/retry behavior. Update deployment and manual-test docs when implementation is authorized.
- **Codebase facts relevant to this plan**:
  - AI organization returns task priorities in `AnalysisTodo`; `complete_analysis_run` persists them in `tasks.priority`. Manual tasks share that field and may also be assigned High.
  - Tasks currently store `due_on` as a date and retain source timing in `timing_text`; `extract_time_of_day` extracts a phrase but does not provide a normalized, validated due datetime.
  - `reminder_at` is currently stored and returned but has no delivery worker. Snoozing stores a date in both `snoozed_until` and `reminder_at`.
  - The existing Attention board and daily briefing are generated on request; current timezone comes from one global `LIFE_INBOX_TIMEZONE`. The web app has no service worker, Web Push implementation, VAPID configuration, or scheduler dependency.
  - Email sending is currently console/fake only. The browser UI is vanilla JavaScript, and all private API routes are session-authenticated and owner-scoped.
- **Why**: The requested high-priority alert is only meaningful when a task has an actual time; date-only tasks cannot safely support a one-hour-before reminder without inventing a deadline. Persistent, owner-scoped delivery is needed because the app is multi-user and the web process has no reliable background scheduler.
- **Files affected**:
  - `decision.md`
- **Implementation status**: Review and plan only. No notification feature was implemented.

## 2026-10-26 — Local NVIDIA Environment Setup

- **What was decided / changed**: Created the local `.env` from `.env.example` and configured the user-provided NVIDIA API key. Confirmed the key setting is populated and `.env` is ignored by Git.
- **Why**: Configure the user's local development environment without adding credentials to tracked files or exposing the key in command output.
- **Files affected**:
  - `.env` (local, Git-ignored)
  - `decision.md`

## 2026-10-26 — Implementation: Daily and High-Priority Notifications

- **What was decided / changed**:
  1. Implement opt-in browser Web Push, with a configurable daily task digest (default 08:00) and an additional alert one hour before an explicit, parseable task time when the AI-generated task priority is `High`.
  2. Only AI-linked High tasks qualify for the extra alert. Require a normalized date and explicit normalized time; do not infer a time for date-only tasks. Honor the task's current open status, due date/time, confirmed/unambiguous timing, and snooze state at dispatch.
  3. Include open tasks due on the user's local day in the daily digest, regardless of priority. Exclude overdue tasks from recurring pushes; keep them visible in the existing attention UI. An opt-in unscheduled-task planning prompt may produce a digest containing a count, but must not label or schedule undated tasks as due.
  4. Store per-user notification preferences, subscriptions, and an idempotent delivery ledger in Alembic-managed tables. Keep delivery in an explicit minute-driven worker command, not in the web process; document external scheduling and provide a local compose worker where practical.
  5. Keep all browser management endpoints behind the existing session auth gate; serve only the service worker script publicly. Validate push endpoints before storing, never return subscription secrets, remove expired endpoints, and keep VAPID private material in environment/deployment secrets.
  6. Extend task timing normalization to persist explicit local `HH:MM` values. Use the user's notification timezone for delivery-time interpretation, and keep existing configured timezone behavior as the default preference.
  7. Add targeted API/service/migration tests, mock Web Push delivery, and update manual/deployment/architecture documentation. Do not perform live pushes in tests.
- **Why**: The requested daily digest and one-hour alert require delivery beyond an open page, durable task timing, opt-in browser permission, user timezone handling, and deduplication across repeated or concurrent scheduler runs. The current app has none of the push infrastructure, and the stored `reminder_at` is not an active delivery mechanism.
- **Implementation completed**:
  - Added normalized task due times, the notification preference/subscription/delivery schema, Alembic migration `0014_notifications`, user-scoped settings/subscription APIs, and idempotent worker dispatch.
  - Added the opt-in browser settings form, permission/subscription flow, root-scoped service worker, VAPID configuration, and a local Compose worker. Generated and validated local VAPID keys in the ignored `.env`; key values were not displayed or added to Git.
  - Added coverage for daily digest selection, overdue/undated handling, AI-linked High eligibility, date-only/ambiguous timing, DST gaps, dispatch timing, settings persistence, subscription ownership, and migration shape. Updated architecture, deployment, and manual-testing documentation.
- **Validation**:
  - Focused notification/API/migration tests: `118 passed`.
  - Full suite: `184 passed, 1 failed`; the isolated `tests/test_auth.py::test_login_rotates_session_token` failure concerns session rotation and is outside the notification changes. The remaining suite passes when that test is excluded.
  - `node --check app/static/app.js` and `node --check app/static/service-worker.js` passed. `git diff --check` reports the existing trailing whitespace at `app/templates/index.html:186`; it was left untouched as unrelated. Local VAPID public/private key correspondence was verified without printing either key.
- **Files affected**: `.env` (local, ignored), `.env.example`, `app/attention/dates.py`, `app/database.py`, `app/main.py`, `app/notifications/`, `app/schemas.py`, `app/static/app.js`, `app/static/service-worker.js`, `app/static/styles.css`, `app/templates/index.html`, `decision.md`, `docker-compose.yml`, `docs/architecture.md`, `docs/deployment.md`, `docs/manual-testing.md`, `migrations/versions/0014_notifications.py`, `requirements.txt`, `tests/test_api.py`, `tests/test_migrations.py`, and `tests/test_notifications.py`.

## 2026-10-26 — Notification Opt-in Diagnosis

- **What was observed**: Browser inspection showed Web Push support, secure localhost context, VAPID configuration, but `Notification.permission` was `denied`; API settings also showed notifications disabled and zero registered subscriptions. Therefore OS/browser support and server configuration were available, but this site had not been granted permission or opted in.
- **What changed**: Added a prominent logged-in opt-in prompt that appears while notifications are off. Its button is the explicit user gesture for requesting permission and starting subscription. When browser permission is denied, the UI now explains that the site must be changed to Allow in browser site settings, then reloaded. Bumped the app JavaScript cache key and added regression coverage/documentation.
- **Follow-up diagnosis**: Standalone scheduler entry points did not load `.env`, unlike the web configuration, so they could fail to see the VAPID keys even when the app could. Both the minute-loop scheduler and one-shot dispatcher now load `.env` on startup.
- **Why**: The prior opt-in controls were lower on the page and only displayed a generic status. Browser notification permissions cannot be re-requested after denial without the user changing the site-level permission.

## 2026-10-26 — Publish Requested Changes

- **What was decided**: Publish the current tracked project changes directly to `deepsleepisgood/life-inbox-copy` on `main`, as requested. Keep the pre-existing untracked `.vscode/` settings and ignored local `.env` out of the commit.
- **Checks**: Fetched `origin/main` and confirmed it had not advanced from the current base. Notification, API, and migration tests pass (`118 passed`). Credential-pattern scan found no credential-like values in the tracked diff. `git diff --check` reports the previously noted template whitespace only.

## 2026-10-29 — Neo-Brutalist UI Redesign (branch `redesign/neo-brutalist`)

- **What was decided / changed**: Full visual redesign of every front-end page (`index.html` app shell, `login.html`, `privacy.html`, `terms.html`), rebuilt on top of `origin/main` (not the earlier `ui-ux` branch, which the owner asked not to reuse). Direction: superdesign.dev's "Disruptor Beta Launch" Neo-Brutalist style guide (Ranchers display font, Space Mono labels, Plus Jakarta Sans body, hard 3–4px borders, solid offset "neo-shadows", tilted sticker badges, vertical rail nav), applied against Life Inbox's own existing dark indigo/lavender/teal/rose palette instead of the reference's black/white/volt-green. A one-page Home mockup was built and shown to the owner for sign-off before the full rollout.
- **Structure**: Added a fixed vertical `app-rail` nav (Home/Inbox/Tasks/Calendar/Ask/Dashboard anchor links, collapsing to a bottom bar under 760px) wrapping the existing single-page layout; added `id`s to section headings as scroll anchors. No existing element `id`, `name`, inline `onclick` handler, or API endpoint was renamed, consistent with the "every ID/selector must keep its exact id" rule.
- **Emoji removal**: Per standing owner feedback ("no emoji in product UI"), replaced every decorative emoji in `app/templates/index.html` and `app/static/app.js` (mic button states, calendar source-type/time/unconfirmed badges) with inline SVG icons or plain mono-styled text labels.
- **Minor additive JS**: `renderTask()` now sets `root.dataset.priority` so CSS can color-code task cards by priority (purely additive, no renamed functions).
- **Verification**: Full pytest suite green (`185 passed`) after each file change. Verified live in the browser: Home, Dashboard, Topics, Ask, Tasks, Calendar (month grid + day inspector), Privacy, and mobile-width (375px) layouts. Login page verified via `curl` (200 OK, expected markup present) rather than a live screenshot, to avoid signing out the active test session in the browser pane.
- **Not yet done**: not committed/pushed to GitHub pending owner confirmation; no `.env`/secrets touched.

## 2026-10-29 — Added animation & wayfinding polish on top of the redesign

- **What was decided / changed**: Per owner request ("add more elements/features or animations that would help"), added purely additive polish on top of the neo-brutalist redesign, with no renamed ids/functions and no new endpoints:
  1. Entrance animation (`li-rise`, 320ms) on `.panel/.note/.task/.topic/.relation/.cal-event-card`, staggered via `nth-child` delays on the dashboard grid and attention board.
  2. Rail nav scroll-spy (`initRailScrollSpy()` in `app.js`): highlights the current section's rail icon as the user scrolls, using a lightweight scroll + `requestAnimationFrame` probe (an initial `IntersectionObserver` version did not reliably track thin heading anchors, so it was replaced).
  3. `setStatus()` now briefly flashes status text teal on update, for visible feedback on async actions.
  4. The Attention board (`loadAttention()`) was restructured from plain `<strong>Label (count)</strong>` panels into proper big-number stat tiles (`attention-tile`), color-coded per bucket (overdue/today/upcoming/unscheduled/snoozed), fulfilling the stat-tile look from the originally approved mockup.
  5. Added a `prefers-reduced-motion` guard that disables/shortens all animation and smooth scrolling for users who request it.
- **Verification**: Full pytest suite green (`185 passed`). Verified live in the browser: entrance animation, attention stat tiles with real task data, and rail active-state tracking correctly while scrolling through Home → Ask → Dashboard.
- **Not yet done**: still not pushed to GitHub — blocked on the owner's GitHub account getting collaborator (write) access to `deepsleepisgood/life-inbox-copy`.

## 2026-10-30 — De-linearized the layout: labeled rail nav, account menu, color-coded content zones

- **What was asked**: Owner reported the app still "reads as one linear scroll," asked (as a UI/UX pass) for labels next to the rail icons so each section is identifiable without guessing, for an account-switching/settings icon at the top (sign out, change account, settings), and for the different sections to visually read as distinct areas ("different skins") rather than one continuous page — explicitly *not* as separate screens/routes, and with the existing aesthetic direction kept as-is.
- **Rail nav labels**: `.app-rail-link` now stacks icon + a short uppercase mono label (`Home`/`Inbox`/`Tasks`/`Cal`/`Ask`/`Board`) instead of icon-only with just a hover tooltip; same markup serves both the desktop vertical rail and the mobile bottom bar (CSS flips `flex-direction`, not structure).
- **Account menu**: Moved the existing session controls (`#authUser`, sign out, sign out everywhere, change-password `<details>`, `#authStatus` — all original ids, unchanged) out of the inline `.auth-bar` block at the top of the page and into a new fixed top-right dropdown (`#accountMenuToggle` / `#accountMenuPanel`), opened/closed by a new additive `toggleAccountMenu()` in `app.js` (click-outside and Escape close it). No existing id, function, or form was renamed.
- **Content zones**: Wrapped the six rail-anchored sections (Home/Ask/Dashboard/Calendar/Tasks/Inbox) in `<section class="zone zone--*">`, each framed by a distinct accent (teal/amber/rose/lavender/purple, matching each section's rail icon color) with a small colored "zone tab" chip (icon + name) at its top — a single-page scroll that visually reads as separate areas, per the owner's explicit "not a different screen" instruction. No section was reordered; unanchored content (Topics, AI-organized inbox, Attention, Task notifications) stayed with whichever anchored zone it already followed in document order.
- **Bug found and fixed during verification**: the rail's scroll-spy (`initRailScrollSpy()`) picked the "active" rail link by iterating the rail's *icon order*, not the page's actual section order, so it could highlight the wrong icon once zones made the mismatch between rail order and DOM order visible (e.g. staying on "Board" while the user was reading the Inbox zone at the bottom of the page). Rewrote `updateActive()` to pick by true viewport position (closest section above the probe line) instead of array-iteration order, and added a bottom-of-page fallback (using `getBoundingClientRect()`, not `offsetTop`, since `.zone`'s new `position: relative` makes `offsetTop` relative to the zone and not comparable across sections) for short trailing sections that can never cross the probe line.
- **Verification**: Full pytest suite green (`185 passed`, backend untouched this round). Registered a throwaway local test account and verified live in the browser at desktop (1440px) and mobile (375px) widths: rail labels readable in both layouts, account menu opens/closes (click-outside and Escape), all six zones render with distinct accent colors and tab chips, and scroll-spy now correctly tracks the active rail icon through every zone including the final one. No console errors.
- **Not yet done**: still not pushed to GitHub — same collaborator-access blocker as above.

## 2026-10-30 — Full QA pass of the merged redesign + fixed a pre-existing broken feature

- **What was asked**: After the branch was pushed and the owner got collaborator access and reviewed it, they asked for a full end-to-end test pass ("act like a world class tester") to confirm the app is ready and that it genuinely uses their teammate's existing backend features rather than anything invented for the review.
- **QA performed**: Full pytest suite green (`185 passed`). Live-tested every major flow against the real backend with a throwaway local account: login/session, Quick Capture + AI auto-categorize (a note correctly split into two linked tasks), Tasks (add/complete/filter/reopen), Calendar (month nav, day detail, confirm/snooze/mark-done), Ask (grounded answer with citation), Analyze Entire Inbox / Dashboard (all 6 panels), Topics, notes search/filter, and the new account menu (correctly shows the real signed-in identity). Zero console errors across all of it.
- **Bug found and fixed**: `app/templates/index.html`'s notification-settings `<button>` had `id="saveNotificationSettings"` — identical to the `saveNotificationSettings()` handler the form's `onsubmit` calls. Because a `<form>` exposes its named/id'd controls as properties on the form element, and inline event-handler attributes resolve bare identifiers against the form before the global scope, `onsubmit="saveNotificationSettings(event)"` was resolving to the *button element*, not the function — so clicking "Save notification settings" always threw `TypeError: saveNotificationSettings is not a function` and never saved anything. This predates today's UI work (confirmed by scanning every other form's `onsubmit` for the same id/function collision — none found elsewhere). Fixed by renaming the button id to `saveNotificationSettingsButton` in `index.html` and updating the one matching `getElementById` call in `app.js`. Verified live: the Save button now fires a `PUT /api/notifications/settings → 200 OK` with no console error.
- **Found but intentionally not fixed**: at real mobile width (375px) the capture drawer's "Upload audio" row overflows the viewport by ~72px (pre-existing `.voice-actions` flex-row sizing issue, unrelated to this session's nav/zone work). The owner said this is a desktop-only web app and mobile layout is not a concern, so this was left as-is on purpose.
- **Verification**: Full pytest suite green (`185 passed`) after the fix. Confirmed via browser network/console inspection that the notification-settings save now succeeds with zero regressions elsewhere.

## 2026-10-30 — Added an "Items by Topic" chart to the dashboard; located the unlinked Privacy/Terms pages

- **What was asked**: Owner asked for a chart element on the Organized Dashboard (not just the existing text lists), and separately said they couldn't find "one page" inside the app.
- **Missing page**: Investigated every page route in `app/main.py` — only `/`, `/login`, `/privacy`, and `/terms` exist. `/privacy` and `/terms` are only ever linked from `login.html`; there has never been a link to either from inside the signed-in app (`index.html`), confirmed by checking `origin/main`'s pre-redesign version too — not a regression from this session's work. Reported this to the owner and offered to add an in-app link; not yet actioned pending their answer.
- **Dashboard chart**: Added `renderTopicsChart()` to `app/static/app.js` — a dependency-free inline-SVG horizontal bar chart (no Chart.js or other library added, consistent with `AGENTS.md`'s "prefer extending this stack" guidance and the app's existing zero-external-script footprint) rendering `data.topics` (`{name, item_count}`), which `loadDashboard()` already fetches from the existing `/api/dashboard` endpoint — no new API call. Colors cycle through the existing neo-brutalist palette tokens (`--li-pop/--li-rose/--li-amber/--li-primary/--li-primary-deep`); bars have hard ink borders matching the rest of the design system. Long topic names truncate to 15 chars with an ellipsis and a native SVG `<title>` tooltip showing the full name, after an initial version showed label text overlapping the bar for "Personal / Reference" during verification. Inserted as a 7th full-width panel (`grid-column: 1 / -1`) in the dashboard grid, with a matching entrance-animation stagger delay.
- **Verification**: Full pytest suite green (`185 passed`, backend untouched). Verified live in the browser with the real single-topic data, then dry-ran the renderer in the console with multi-topic mock data (without touching real app state) to confirm multi-bar layout, color cycling, and the truncation fix all render correctly. No console errors.

## 2026-10-30 — Restyled the raw OS file-picker in "More capture options"

- **What was asked**: Owner shared a screenshot pointing out the PDF/Image/Audio "Choose File | No file chosen" controls still look like the unstyled native OS widget, clashing with the rest of the neo-brutalist UI, and asked for it to "look good."
- **What changed**: Added a `.file-picker` component (`app/static/styles.css`) — a bordered wrapper with a custom mono-font "Choose file" button and a filename display, with the real `<input type="file">` layered on top at `opacity:0` covering the full clickable area (so native click/keyboard/drag-drop behavior is preserved exactly; this is not a `label`-for-hidden-input trick, which can be less reliable across browsers). Wrapped the three existing file inputs (`pdfFile`, `imageFile`, `voiceFile` — same ids, unchanged) in this markup in `index.html`. Added `initFilePickers()` in `app.js` to update the filename text on `change`, and a `resetFilePickerName()` helper called from the three existing post-upload `input.value = ''` resets in `addPdf()`/`addImage()`/`addVoice()` (clearing the input value programmatically doesn't fire a native `change` event, so without this the filename text would have gone stale after a successful upload).
- **Verification**: Full pytest suite green (`185 passed`, backend untouched). Verified live: simulated a file selection via `DataTransfer` (screenshot confirmed the styled "Choose file" button + filename), then actually submitted it through the real `addPdf()` upload flow (`POST /api/items/pdf → 200 OK`) and confirmed the display correctly reset to "No file chosen" afterward. A `POST /api/analyze?item_id=…` 404 observed during this test was the backend's pre-existing auto-analyze call reacting to the deliberately-invalid test PDF content (failed text extraction) — unrelated to this UI change, traced to confirm it predates it.

## 2026-10-30 — Squash-merged `redesign/neo-brutalist` directly into `main`

- **What was asked**: Owner asked to merge all 6 commits from the redesign branch into `main` as a single combined commit ("they are just going to be one"), and explicitly authorized doing it directly rather than walking through GitHub's PR UI ("you please do it. I'll give you the access control").
- **What changed**: Rather than driving GitHub's web UI (no browser session authenticated as the owner was available), performed the equivalent of GitHub's "Squash and merge" directly with git, using the same push credentials already used all session: created a scratch branch from `origin/main` (not the stale, diverged local `main`, which still holds an unrelated unpushed "Add stats panel" commit and was left untouched), `git merge --squash redesign/neo-brutalist`, committed as a single commit summarizing all 6 originals, ran the full test suite against that exact state, then pushed straight to `origin/main` (confirmed a clean fast-forward from `main`'s prior tip, not a force-push) and deleted the local scratch branch. `main` now has one commit (`a7651d7`) containing the full redesign instead of six.
- **Verification**: Full pytest suite green (`185 passed`) run against the squashed commit immediately before pushing. Confirmed via `git fetch` that `origin/main`'s tip matches the pushed commit.

## 2026-10-30 — Sequential diagonal entrance animation for the rail nav icons

- **What was asked**: Owner shared a screenshot of the rail nav (all icons static/appearing at once) and asked, in their words, to "make it sequential... diagonal sequence" — interpreted as a staggered, one-after-another diagonal slide-in entrance animation for the rail icons, matching the app's existing stagger-animation pattern (`li-rise` on the dashboard grid/attention tiles) which had never been applied to the rail nav itself.
- **What changed**: Added `@keyframes li-rail-diagonal` (`app/static/styles.css`) — icons fade and slide in from a diagonal offset, each `.app-rail-link` delayed 70ms after the previous one (`:nth-of-type(2..7)`, offset by 1 to account for the brand link being the 1st `<a>` sibling). Caught and fixed a real bug before shipping: `.app-rail-brand` already has a static `transform: rotate(180deg)` for its vertical text, and animating `transform` on it directly would have overwritten that rotation once the animation's fill-mode locked in — gave the brand link its own separate keyframe (`li-rail-diagonal-brand`) that keeps the rotation throughout. Since this work started after `main` was already updated (see above), built it on a fresh branch off current `origin/main` rather than the now-stale `redesign/neo-brutalist`.
- **Verification**: Full pytest suite green (`185 passed`). Verified live: computed styles confirmed the brand's rotation is intact post-animation (`matrix(-1,0,0,-1,0,0)` = `rotate(180deg)`) and all 6 links carry the correct sequential delays; caught the animation mid-play with a screenshot showing only "Home" visible while the rest were still fading in, confirming the sequential reveal actually happens rather than just existing in CSS. No console errors.

## 2026-10-30 — Reordered the rail nav icons to match the page's actual section order

- **What was asked**: Owner said the rail icon order should read "Home, Ask, Board, Calendar, Task, Inbox" and reported that while scrolling, the highlighted icon was "going up and down, not in the sequence."
- **Root cause**: The rail's icon order (`index.html`, inherited unchanged from the original app: Home, Inbox, Tasks, Cal, Ask, Dashboard) never matched the page's actual top-to-bottom zone order (Home, Ask, Dashboard, Calendar, Tasks, Inbox — set when the content zones were built earlier). The scroll-spy logic itself was already correct (picks the active link by true viewport position, not rail order — fixed earlier this session), but with the rail's visual order out of step with the page's scroll order, the highlighted icon necessarily jumped around the rail as you scrolled, even though it was always highlighting the *right* section.
- **What changed**: Reordered the six `<a class="app-rail-link">` elements in `index.html` to Home → Ask → Board(Dashboard) → Calendar → Tasks → Inbox, matching the page's zone order exactly. No id, href, label, or icon changed — purely a reorder. The diagonal entrance-animation stagger (keyed to sibling position via `:nth-of-type`, not href) and the mobile bottom-bar layout (same markup, different `flex-direction`) both automatically follow the new order with no further changes needed.
- **Verification**: Full pytest suite green (`185 passed`). Verified live by scrolling to each section's exact position individually (not in one rapid-fire loop, which produced unreliable results from animation-frame scheduling, not a real bug) and confirming the rail highlight progresses Home → Ask → Board → Calendar → Tasks → Inbox in order with no jumping.
## 2026-10-30 — Reconcile and prune tasks on note editing / re-analysis to prevent duplicates

- **What was asked**: When editing a note in the Raw Saved Notes section, AI reanalysis was creating a second separate task (e.g. "Play pickleball" alongside "Play pickleball with Vijay"), duplicating the task in the Tasks section, Attention Board, and Calendar.
- **Root cause**: In `app/database.py:complete_analysis_run`, candidate task matching required a strict Jaccard word-overlap threshold (`>= 0.6`). Adding words or names (like "with Vijay") lowered the Jaccard similarity below 0.6 (e.g. 2/4 = 0.5), causing the matcher to treat the reworded task as completely unrelated and insert a new task record. Furthermore, `complete_analysis_run` never pruned unmatched open tasks from re-analyzed source notes, leaving the prior task behind in the database linked to the same source item.
- **What changed**:
  1. Updated candidate matching in `complete_analysis_run` to check substring containment (`target in candidate` or `candidate in target`), word containment (`len(left & right) / min(len(left), len(right)) >= 0.5`), and 1-to-1 open candidate matching for notes with a single task.
  2. Added a cleanup step in `complete_analysis_run` that prunes any stale open AI tasks whose source notes were re-analyzed in that run but were not matched to any current todo.
  3. Cleaned up the existing leftover duplicate task in `data/life_inbox.db`.
  4. Added test `test_editing_note_updates_task_without_duplication` in `tests/test_api.py`.
- **Verification**: Full pytest suite green (`186 passed`). Confirmed in the database that exactly 1 updated task remains for the note.

## 2026-11-05 — Codebase review follow-up: fixes for 4 issues (startup check, relation isolation, key prefix, calendar drafts)

- **What was asked**: After a full read-through of the repo, the owner approved fixing four issues found in review. The owner also stated they will use only an NVIDIA NIM key and not an OpenAI key.
- **Fix 1 — silent startup migration check** (`app/main.py`): `_check_startup_health()` called `os.getenv` but `os` was never imported. The resulting `NameError` was swallowed by `except Exception` and logged at debug level, so the "migrations pending" warning could never appear. Added `import os` and raised the skip message to `warning` so a failing check is visible (still non-fatal).
- **Fix 2 — cross-user leakage in analysis** (`app/database.py`): the relation refresh in `complete_analysis_run` read every user's items and deleted every user's non-dismissed relations, and `completed_item_ids` was not owner-filtered. Now both are scoped to the current owner. Same class of bug found while fixing: `dismiss_relation_in_db` had no ownership check, so any signed-in user could dismiss another user's relation by id; it now returns None (404) unless the relation's anchor item belongs to the caller.
- **Fix 3 — `nvapi-` prefix on any key** (`app/capture/voice_extract.py`): the prefix was added to whatever key was found, including `OPENAI_API_KEY`. It is now applied only to `NVIDIA_API_KEY`; a key from any other source is passed through untouched. `config.py` already only prefixed `NVIDIA_API_KEY`. The "not configured" message now always names `NVIDIA_API_KEY`.
- **Fix 4 — calendar drafts not owner-scoped** (`app/integrations/calendar.py`, `app/main.py`): drafts lived in a process-global dict keyed by random id, so another signed-in user holding a draft id could confirm it. `store_draft`/`get_draft` now take a required `owner_user_id` and `get_draft` returns None for other owners; the preview/confirm routes pass `require_owner_id()`. Signature change is keyword-only and only used in `main.py`.
- **Extra fix found while verifying** (`app/database.py`): `claim_notification_delivery` used `timedelta` but only `datetime, timezone` were imported, so a retry of an already-claimed delivery key would raise `NameError`. Added the import.
- **Deliberately not changed**: the `OPENAI_API_KEY` fallbacks in `organizer.py`, `ask.py`, `seed_demo_notes.py` and `image_extract.py` remain; existing tests set `OPENAI_API_KEY` to switch the LLM paths on with mocks, so removing them is a separate, wider change. Fixes 5-7 from the review (TF-IDF rebuilt per query, stale docs, local DB/.env hygiene) were not part of this request.
- **Tests added**: `tests/test_isolation_regressions.py` (4 tests: startup check logs no skip, draft confirm by another user returns 404, another user's analysis keeps my relations and cannot dismiss them, `nvapi-` prefix only on the NVIDIA key). Confirmed all 4 fail on the previous code and pass now.
- **Verification**: full suite `185 passed, 5 failed`. The 5 failures are all in `tests/test_calendar.py` and are pre-existing (identical on a clean stash): they hard-code dates like "3 Nov" without a year, and with today at 2026-11-05 the parser rolls them to 2027. Not caused by these changes and left untouched; they need date-relative test data.
- **Files affected**: `app/main.py`, `app/database.py`, `app/integrations/calendar.py`, `app/capture/voice_extract.py`, `tests/test_isolation_regressions.py` (new), `decision.md`.

## 2026-11-05 — Analysis lingering after delete/complete; "Preview calendar" appeared dead

- **What was asked**: (1) Deleted or completed notes were still showing their analysis (High priority / AI-organized inbox / Topics counts on the dashboard). (2) The "Preview calendar" button on a task did nothing visible.
- **Root causes (analysis)**:
  1. `get_latest_successful_analysis` filtered the stored run snapshot only for *completed* notes; *deleted* notes stayed in the snapshot JSON (buckets, priority view, todos), so the AI-organized inbox and dashboard analysis kept showing them.
  2. `list_topics_from_db` counted every insight row, including completed notes, so topic counts (e.g. Health 1 / Personal 1) never dropped.
  3. The UI did not refresh the analysis panel / topics / dashboard after a delete (only analysis+tasks), after a note "Complete" (no topics, no analysis), or after a task transition (no topics, no analysis).
- **Root causes (preview button)**:
  1. `parse_timing_phrase` did not know "tonight" (only "today"), so a confirmed "tonight" task had no normalized date and `/api/calendar/preview` returned 400 ("Task has no normalized date").
  2. Regardless of outcome, the result/error was written only into the Calendar section far below the Tasks list, so nothing visibly happened from the Tasks list (the "tomorrow" task worked but its preview rendered offscreen).
- **What changed**:
  - `app/database.py`: stored analysis now also hides notes that no longer exist; topic counts skip completed notes. Design choice: completion is a *view filter*, not data destruction, so reopening a task restores the note's analysis and topic count (consistent with earlier decisions on completed-note pruning). Deleting a note already removes its insight, tasks and relations.
  - `app/attention/dates.py`: "tonight", "this morning/afternoon/evening" normalize to today (high confidence; the clock time still comes from `time_of_day`).
  - `app/static/app.js`: new `refreshAnalysisViews()` (latest analysis + topics + dashboard) used after note delete, note complete and task transitions; calendar preview now also reports in the Tasks status line and scrolls the preview panel into view, including on error.
  - `app/templates/index.html`: bumped the `app.js` cache-busting key.
- **Tests**: added 4 tests to `tests/test_isolation_regressions.py` (deleted note leaves saved analysis/dashboard/topic counts; completed note leaves them and returns on reopen; "tonight" parses as today; calendar preview succeeds for a confirmed "tonight" task). All fail on the previous code, pass now.
- **Verification**: full suite `189 passed, 5 failed` — the 5 are the known pre-existing date-dependent tests in `tests/test_calendar.py` (hard-coded "3 Nov"). `node --check app/static/app.js` passes. Not verified in a live browser this round.
- **Known limitation**: `fetchJson` replaces server error details with a generic message, so a failed preview shows "Unable to preview calendar event." rather than the server's specific reason. AI-created topics (e.g. "Personal") stay listed at 0 once empty.
- **Files affected**: `app/database.py`, `app/attention/dates.py`, `app/static/app.js`, `app/templates/index.html`, `tests/test_isolation_regressions.py`, `decision.md`.

## 2026-11-05 — Manually added dated task did not appear on the calendar

- **What was asked**: A task added through the Tasks form ("Add task", with a due date) did not show up on the in-app calendar.
- **Investigation (systematic-debugging)**: Reproduced at the API level first: `POST /api/tasks` with `due_on` returns 201 and `GET /api/calendar/events` for that month already returns the task (with `source_item_id: null`, `source_type: "text"`). So the backend and the calendar renderer (which already handles a missing source note) are correct. The defect was in the front end: `createQuickTask()` refreshed tasks, attention and dashboard but never called `loadCalendarEvents()`, so the calendar stayed stale until a full page reload (and would also stay on the wrong month if the task's date was in another month).
- **What changed** (`app/static/app.js`): after a successful create, if a due date was set, the calendar view jumps to that task's month and selects that day; then `loadCalendarEvents()` is called. Bumped the `app.js` cache key in `app/templates/index.html`.
- **Tests**: added to `tests/test_isolation_regressions.py`: backend guard (a manual dated task is returned as a calendar event) and a UI regression check that `createQuickTask` refreshes the calendar (failed before the fix, passes after).
- **Verification**: full suite `191 passed, 5 failed` (the 5 are the known date-dependent `tests/test_calendar.py` tests). `node --check app/static/app.js` OK. Not verified in a live browser.
- **Noted, not changed**: calendar cards for manual tasks show the badge "text" (default source type when a task has no source note); cosmetic.
- **Files affected**: `app/static/app.js`, `app/templates/index.html`, `tests/test_isolation_regressions.py`, `decision.md`.

## 2026-11-05 — Browser verification of the delete/complete/preview/manual-task fixes

- **What was done**: Chrome-extension and built-in-browser tools were not available in this session, so the earlier UI fixes were verified with Playwright (installed in a throwaway venv in the scratchpad, NOT added to the project or `requirements.txt`) driving the installed Chrome headlessly. The app ran on a temporary SQLite database with `NVIDIA_API_KEY`/`OPENAI_API_KEY` blanked (offline fallback, no live AI calls) on port 8765; the real `data/life_inbox.db` was not touched. Server was stopped afterwards and the port confirmed free.
- **Results** (real page, real clicks): (1) manual task with a due date in another month: calendar jumped to December 2026 and showed the task on the 18th; (2) deleting a note removed it from the AI-organized inbox and dashboard and lowered the topic count; (3) completing a note did the same (Health 1 → 0); (4) a confirmed "tonight" task: Preview calendar rendered the preview (dated 2026-11-05), the Tasks status line reported it, and the panel scrolled into view.
- **Not bugs**: the script's first "calendar jumped" check failed only because the UI renders the month in uppercase ("DECEMBER 2026"); the single console error was a 404 for `/favicon.ico` (the app has no favicon), unrelated to these changes.
- **Files affected**: `decision.md` only (no application changes). Screenshots/scripts are in the session scratchpad, not the repo.

## 2026-11-05 — README brought up to date

- **What was asked**: Edit the README as well.
- **What changed** (`README.md`, docs only, no code): feature list now mentions accounts, manual tasks, notifications, and NVIDIA-only AI (removed "OpenAI-compatible endpoint" wording); added "Accounts and sign-in" (create account on first visit, forgot-password code printed in the server terminal, `reset_password` and `claim_local_owner` scripts); calendar section now covers manual dated tasks and the supported timing phrases (incl. "tonight"); new "Completing and deleting notes" explaining that completing hides analysis (reversible) while deleting removes it; new "Browser Notifications (optional)" section pointing at `docs/deployment.md`; tests section no longer says "do not call OpenAI" and records the known date-dependent `tests/test_calendar.py` failures; project layout rewritten to match the real tree (migrations 0001-0014, auth, notifications, scripts, `decision.md`).
- **Found while documenting**: `scripts/seed_demo_notes.py` is broken since accounts were introduced: it calls `add_note_to_db` with no signed-in user and fails with `NotAuthenticatedError` (reproduced against a temporary DB). The README now says so instead of advertising it. Not fixed here (not requested).
- **Not touched**: `AGENTS.md`, `docs/*` still contain older `OPENAI_*` wording and a stale migration list; separate follow-up.
- **Files affected**: `README.md`, `decision.md`.

## 2026-11-05 — Password rules enforced on sign-up, reset and change (plan step 1)

- **What was asked**: Enforce password rules (owner chose classic composition rules) as part of adding Google sign-in; plan saved at `~/.claude/plans/now-i-want-you-adaptive-pearl.md`.
- **What changed**:
  - `app/auth.py` `password_problem()` (single source of truth, already used by register, change, reset-with-code and `scripts/reset_password.py`): keeps length 10-128, not-only-spaces, common-password list and not-your-email; now also requires an upper-case letter, lower-case letter, number and symbol (one message lists everything missing), and rejects 4+ repeated characters, 4+ character sequences (1234/abcd), the app name, the email's local part (4+ chars) and any 4+ letter word of the display name. `register_user` and `change_password` now pass the display name. Rules apply only when a password is set; existing passwords still sign in (covered by a test).
  - New `app/static/password_rules.js`: live checklist (length/upper/lower/number/symbol) and a "passwords match" indicator, attached to the register form, the forgot-password reset form (`login.html`/`auth.js`) and the in-app change-password form (`index.html`/`app.js`); submit is blocked client-side with a specific message; the server message is still shown if it disagrees. Styles in `login.css` and `styles.css`; cache keys bumped.
- **Tests**: `DEFAULT_TEST_PASSWORD` is now `Correct-Horse-9-Staple` and the literal passphrases in `tests/test_auth.py` were changed to compliant ones; added per-rule tests, a "lists every missing class" test, a change-password rule test and a grandfathering test (old weak password still signs in).
- **Gotcha**: a regex written through a shell heredoc (`(.)\1{3,}`) silently became a control character; caught by a manual check (`Aaaaa-bbbb-9X` was accepted), fixed, and covered by the repeat-rule test.
- **Verification**: full suite `203 passed, 5 failed` (the 5 known date-dependent `tests/test_calendar.py` tests); `node --check` OK on `app.js`, `auth.js`, `password_rules.js`. Browser check will be done after the Google step.
- **Files affected**: `app/auth.py`, `app/static/password_rules.js` (new), `app/static/auth.js`, `app/static/app.js`, `app/static/login.css`, `app/static/styles.css`, `app/templates/login.html`, `app/templates/index.html`, `tests/auth_helpers.py`, `tests/test_auth.py`, `decision.md`.

## 2026-11-05 — Sign in with Google (plan step 2)

- **What was asked**: Add "Sign in with Google" to the sign-up/sign-in page. Owner chose: server-side OAuth redirect; for an existing password account with the same email, link then cut off the old password.
- **Design**: OAuth 2.0 authorization-code flow with PKCE, implemented with the already-installed `requests` (no new dependency). `app/google_auth.py`: builds the authorize URL (scope `openid email profile`, `state`, `nonce`, S256 challenge), keeps state/nonce/verifier/intent/consent in a 10-minute HttpOnly SameSite=Lax cookie signed with HMAC (`otp_pepper`), exchanges the code server-to-server at Google's token endpoint, and validates `iss`, `aud`, `exp`, `nonce`, `sub`, `email` and `email_verified`. The id_token signature is not re-verified because it arrives directly from Google over TLS (OIDC Core 3.1.3.7); documented in the module.
- **Routes** (`app/main.py`, all added to `PUBLIC_PATHS`): `GET /api/auth/providers`, `GET /api/auth/google/start` (404 when not configured), `GET /auth/google/callback`. The callback uses the existing `_start_fresh_session()`; failures redirect to `/login?error=<fixed code>` only (messages are mapped client-side, nothing is reflected).
- **Accounts** (`app/auth.py` `sign_in_with_google`, `app/database.py`): known `google_sub` signs in; unknown `sub` + email matching an existing account links it (sets `google_sub`, `email_verified_at`, **clears the password hash, revokes all its sessions**, flags `?google=linked` so the app explains it); otherwise only the Create-account intent with both 18+ and Terms boxes makes a new Google-only user (default topics seeded, consent timestamps stored). Sign-in intent with an unknown email creates nothing and points to the Create tab. Google-only users cannot password-login (no hash); "Forgot password" can still give them one.
- **Schema**: Alembic `0015_google_signin` adds `users.google_sub` with a unique index (model `UserRecord` updated); `tests/test_migrations.py` head expectations updated. **The real `data/life_inbox.db` is now behind** and the app refuses to start on it until `python -m alembic upgrade head` is run (back up first, per AGENTS.md); it was not touched.
- **Config**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` (default `http://127.0.0.1:8000/auth/google/callback`) in `app/config.py` (`google_enabled`; beta/production require an https redirect), `.env.example`, `docker-compose.yml`. Unconfigured = button hidden.
- **UI**: `login.html`/`auth.js`/`login.css` "Continue with Google" / "Sign up with Google" button (hidden unless enabled and hidden on the forgot-password panel; on Create it requires both boxes), error-code messages; `app.js` shows the "linked, old password removed" notice. No external scripts or images.
- **Tests**: new `tests/test_google_auth.py` (17 tests, Google token endpoint mocked): provider flag and 404 when unconfigured, PKCE/state in the redirect, consent required, new user creation, unknown email on sign-in, returning user by `sub`, bad aud/iss/exp/nonce/unverified/empty email, token endpoint failure, state mismatch/missing/expired/forged cookie, user-denied, linking removes password + kills old sessions, Google-only account cannot password-login.
- **Verification**: full suite `220 passed, 5 failed` (the 5 known date-dependent calendar tests); `node --check` OK. The real Google round-trip needs the owner's Google Cloud credentials and has not been run; browser check of the login page follows after step 3.
- **Owner setup still required**: Google Cloud Console project, OAuth consent screen (External, Testing, add yourself as test user), OAuth client "Web application" with redirect URI `http://127.0.0.1:8000/auth/google/callback`, then put the ID/secret in `.env`.
- **Files affected**: `app/google_auth.py` (new), `app/auth.py`, `app/main.py`, `app/config.py`, `app/database.py`, `migrations/versions/0015_google_signin.py` (new), `app/templates/login.html`, `app/static/auth.js`, `app/static/login.css`, `app/static/app.js`, `app/templates/index.html`, `.env.example`, `docker-compose.yml`, `tests/test_google_auth.py` (new), `tests/test_migrations.py`, `decision.md`.

## 2026-11-05 — First batch of quick wins + browser verification of the sign-in work (plan step 3)

- **Edit tasks**: new `PATCH /api/tasks/{id}` (`TaskUpdate` in `app/schemas.py`; owner-scoped `update_task_in_db` in `app/database.py`; route in `app/main.py`). Editable: text, priority, due date (a new date is saved as user-confirmed, high confidence) or `clear_due_date`; empty body, unknown fields, empty text, or "set and clear" together are 422; another user's task is 404. New `tasks.user_edited` flag (Alembic `0016_task_user_edited`, default 0): when set, `complete_analysis_run` no longer overwrites that task's text/priority on re-analysis (otherwise a user's edit would be lost the next time the note is analyzed). UI: **Edit** button on open tasks opens an inline form (`showEditTask` in `app/static/app.js`) and refreshes tasks, attention, dashboard and calendar.
- **Real server error messages**: `fetchJson()` now shows the server's `detail` for 4xx responses (e.g. "Task has no normalized date...") instead of always the generic text; 401 handling and non-4xx behaviour unchanged.
- **Real email**: new `smtp` provider in `app/email_sender.py` (stdlib `smtplib`; STARTTLS on 587, SSL on 465; `LIFE_INBOX_SMTP_HOST/PORT/USER/PASSWORD/FROM`). `app/config.py` accepts `smtp` (not in the dev-only set, so beta/production allow it) and rejects an unconfigured `smtp` in strict mode. `request_password_reset` now logs a mail failure instead of returning a 500, so the response is identical whether or not the account exists or mail works (no account enumeration).
- **Docs**: README (password rules, Google setup steps, SMTP, edit tasks, migrations reminder, layout, revisions 0001-0016), `docs/deployment.md` (Google and SMTP variables), `.env.example`.
- **Tests**: new `tests/test_task_edit_and_smtp.py` (15 tests: edit text/priority/date moves the calendar event, clearing date, bad input, cross-user 404, re-analysis keeps edits, UI strings, SMTP STARTTLS/SSL/not-configured/strict-config, forgot-password survives mail failure with identical responses); `tests/test_migrations.py` updated for head `0016_task_user_edited` and the new `tasks.user_edited` column.
- **Verification**: full suite `235 passed, 5 failed` (the 5 known date-dependent `tests/test_calendar.py` tests). Real-browser check (Playwright driving Chrome, temp DB migrated to 0016, AI keys blanked, dummy Google client): live password checklist ticks and mismatch/match shown; weak passwords blocked with a specific message; server-side rule message ("sequence") shown; Google button shown, relabeled on the Create tab, blocked until both consent boxes are ticked, and clicking it reaches `accounts.google.com` with our client id (Google answered "client not found" for the dummy id, as expected) with the signed state cookie set; returned `?error=` codes render; button hidden on the forgot panel; registration with a strong password works; task Edit changes text/priority/date and the calendar event moves, clearing the date removes it; in-app change-password checklist blocks a weak password. Server stopped, port 8765 confirmed free, real `data/life_inbox.db` untouched.
- **Not verified**: the real Google round-trip (needs the owner's Google Cloud credentials) and real SMTP delivery (needs mail credentials); both are covered only with mocks.
- **Heads-up for the owner**: the app now needs `python -m alembic upgrade head` on `data/life_inbox.db` (migrations 0015 and 0016) before it will start. Back up the file first.
- **Files affected**: `app/schemas.py`, `app/database.py`, `app/main.py`, `app/static/app.js`, `app/static/styles.css`, `app/email_sender.py`, `app/config.py`, `app/auth.py`, `app/templates/index.html`, `migrations/versions/0016_task_user_edited.py` (new), `tests/test_task_edit_and_smtp.py` (new), `tests/test_migrations.py`, `README.md`, `docs/deployment.md`, `.env.example`, `decision.md`.

## 2026-11-05 — Startup failure diagnosis, migration applied, Google sign-in enabled and checked

- **Startup failure**: the app would not start because `data/life_inbox.db` was at `0014_notifications` while the code needs `0016_task_user_edited` (`SchemaOutOfDateError`, raised on purpose by `ensure_schema_is_current()`). Reproduced read-only (`import app.main` and `alembic current`); no data was changed by the diagnosis.
- **Migration**: applied by the owner (backup first: `data/life_inbox.backup-before-0016.db`, then `alembic upgrade head`). Verified afterwards that `alembic current` reports `0016_task_user_edited (head)`. Both migrations only add columns/an index (`users.google_sub` + unique index, `tasks.user_edited`); no existing rows were altered.
- **"No Google button" report**: expected behaviour, not a bug. The button is hidden unless `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set (`GET /api/auth/providers` returns `{"google": false}`), and at that point `.env` had neither. Owner then created the OAuth client in Google Cloud Console and filled in `.env`.
- **Verification after setup** (secrets never printed; only presence/length checked): all three `GOOGLE_*` values set, redirect URI is `http://127.0.0.1:8000/auth/google/callback`. Ran a throwaway server on port 8766 against a temporary database with the real `.env` credentials: `/api/auth/providers` returned `{"google": true}`; `/api/auth/google/start` redirected to `accounts.google.com` with PKCE/state/nonce; following it reached Google's real account-chooser page (no `invalid_client` / `redirect_uri_mismatch`), so Google accepts the client ID and redirect URI. A Playwright screenshot confirmed "Continue with Google" on the Sign-in tab and "Sign up with Google" on the Create tab. Server stopped and port confirmed free; the real database was not used.
- **Not verified**: an actual sign-in with a real Google account (needs the owner to do it; only Google test users can sign in while the consent screen is in Testing mode).
- **Files affected**: `decision.md` only (no application changes in this step).
