# Product roadmap

Life Inbox evolves through cumulative milestones. Each milestone must remain
understandable, testable, and recoverable for a teaching program.

## Milestone 1 — Polished, trustworthy core

Reliable capture / list / edit / delete; durable tasks; stale analysis marking;
pagination; Alembic-owned schema; coherent UI; CI; smoke checklist.

## Milestone 2 — Intelligent organization / second brain

User-editable topics/spaces; AI suggestions (title, topic, priority, tasks,
dates, tags); preserve user corrections; duplicates/related items; multi-task
per source; organized dashboard.

## Milestone 3 — Rich capture

Shared ingestion lifecycle: capture → save original → process → extract →
understand → organize → ready/failed.

- **3A** URL / article capture (done)
- **3B** PDF / document upload (done)
- **3C** Images / screenshots (+ OCR adapter) (done)
- **3D** Voice notes (+ transcription adapter) (done)

## Milestone 4 — Retrieval + grounded “Ask My Inbox” (done)

Keyword + lightweight semantic retrieval; citations; insufficient-evidence
honesty; evaluation fixtures.

## Milestone 5 — Attention, reminders, safe actions (done)

Deadline views; in-app reminders; optional Google Calendar behind an adapter
with preview + explicit confirmation only.

## Milestone 6 — Deployable multi-user beta (done)

Auth, ownership scoping, Postgres for prod, storage abstraction, health,
deployment guide. Stop before paid infra / public deploy without approval.

## Milestone 7 — NVIDIA NIM AI & Voice Note Taking (done)

Migration of AI provider to NVIDIA NIM (OpenAI-compatible endpoints) with `.env` loading; 4-state browser voice recording (idle, recording with pulsing indicator + timer, transcribing spinner, error) with MediaRecorder and ffmpeg 16kHz WAV conversion; NVIDIA NIM ASR (`openai/whisper-large-v3`) + strict NIM LLM transcript cleanup (`meta/llama-3.1-70b-instruct`) preserving all facts while stripping filler words and stutters; voice note edit/delete in UI; frictionless onboarding via setup scripts (`setup.sh`, `setup.ps1`) and non-blocking startup sanity checks.

## Life Inbox v2, Phases 4–7 (built 2026-11-09, not pushed)

See `docs/design/life-inbox-v2-build-plan.md` and `docs/changes/016-…` to `024-025-…`.

- **Phase 4 — Memory**: what Life Inbox learns about you (016), with secrets kept out of view, AI and
  memory; memory hints in filing and plan updates (017, off until the live replay is approved).
- **Phase 5 — Helpers**: Scout's catch-ups (018), Ask me v2 with checked citations (019), the weekly
  review with topic proposals, area summaries and Captain's daily greeting (020).
- **Phase 6 — Better sources**: OCR for images and a vision call when there's no text (021), PDFs with
  formulas, scans and a one-time summary (022), editing your note on a source (023).
- **Phase 7 — Ready for beta**: onboarding (024); the AI switch, account deletion and the privacy and
  terms pass (025).

Still open: install Tesseract (owner), the live replays (014 and 017, they spend credits), a published
grievance/privacy contact, and the review and push.

## Execution priority (time-constrained)

M1 (fast) → M2 showcase → M3A → M3B → M4 → M3C images → M3D voice → M5 → M6 → M7.
