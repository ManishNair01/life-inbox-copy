# Change log for review

Changes made in this copy of Life Inbox that have **not been pushed yet**.
Each change has its own document covering the problem, the solution, the
files changed, how it was tested and anything to know before pushing.

| # | Change | Date | Status |
|---|---|---|---|
| 001 | [Quick Capture stops at 2000 characters](001-note-character-limit.md) | 2026-11-02 | Done, not pushed |
| 002 | [Topics with descriptions and AI-suggested subtopics](002-topics-and-subtopics.md) | 2026-11-02 | Done, not pushed |
| 003 | [Delete user-created topics, and re-home their notes](003-delete-topics.md) | 2026-11-02 | Done, not pushed |
| 004 | [Fix AI creating near-duplicate topics; dashboard shows subtopics](004-ai-topic-name-fix.md) | 2026-11-02 | Done, not pushed (fixes 002) |
| 005 | [Add a source together with your own note (one composer)](005-sources-with-context.md) | 2026-11-02 | Done, not pushed |
| 006 | [One path for every AI call, and Ask's NVIDIA 404](006-one-path-for-ai-calls.md) | 2026-11-02 | Done, not pushed |
| 007 | [Privacy policy names NVIDIA and explains link fetching](007-privacy-nvidia-and-links.md) | 2026-11-02 | Done, not pushed |
| 008 | [The five life areas](008-five-life-areas.md) | 2026-11-02 | Done, not pushed |
| 009 | [The three-pane app, with Home, the lens and the note page](009-three-pane-app.md) | 2026-11-04 | Done, not pushed |
| 010 | [Topics and spaces, and the topic page](010-topics-and-spaces.md) | 2026-11-05 | Done, not pushed |
| 011 | [Timeline, Calendar, Priority and Dashboard](011-timeline-calendar-priority-dashboard.md) | 2026-11-05 | Done, not pushed |
| 011a | [Capture from anywhere, and hover cards](011a-capture-anywhere-and-hover-cards.md) | 2026-11-07 | Done, not pushed (added after phase 2 at your request) |
| 012 (part 1) | [Change any date, postpone in place, and confirm again after an edit](012-dates-part-1-change-and-postpone.md) | 2026-11-07 | Done, not pushed |
| 012 (part 2) | [Where each date came from, the small calendar, and asking right after saving](012-dates-part-2-where-dates-come-from.md) | 2026-11-07 | Done, not pushed |
| 013 | [Captain's "Needs you" list](013-captain-needs-you.md) | 2026-11-08 | Done, not pushed |
| 014 | [Filing v2, one checked AI call per note](014-filing-v2.md) | 2026-11-08 | Done, not pushed (live NVIDIA check still to run) |
| 015 | [Smart link capture](015-smart-link-capture.md) | 2026-11-08 | Done, not pushed |
| 014a | [Thought-to-action: ask before a maybe becomes a task](014a-thought-to-action.md) | 2026-11-08 | Done, not pushed (from the owner's backlog) |
| 015a | [Hobbies, with Cooking inside it](015a-hobbies-and-cooking.md) | 2026-11-08 | Done, not pushed |
| 016 | [Memory: what Life Inbox learns about you, and secrets in notes](016-memory.md) | 2026-11-09 | Done, not pushed |
| 017 | [Memory in filing, and plan updates](017-memory-in-filing.md) | 2026-11-09 | Done, not pushed (off until the owner OKs the live replay) |
| 018 | [Scout, the catch-up helper](018-scout.md) | 2026-11-09 | Done, not pushed |
| 019 | [Ask me v2](019-ask-me-v2.md) | 2026-11-09 | Done, not pushed |
| 020 | [Weekly review, topic proposals, bot summaries and the greeting](020-weekly-review.md) | 2026-11-09 | Done, not pushed |
| 021–023 | [Better sources: text in images, PDFs with formulas and scans, editing your note on a source](021-023-better-sources.md) | 2026-11-09 | Done, not pushed (Tesseract still to install) |
| 024–025 | [Ready for beta: onboarding, the AI switch, deleting your account, privacy](024-025-ready-for-beta.md) | 2026-11-09 | Done, not pushed (push waits for the owner's OK) |

**Planned next:** phase 3 is done; try it, then phase 4 (016–017), in `docs/design/life-inbox-v2-build-plan.md`.

## Before pushing all changes

1. Run the full test suite: `.\.venv\Scripts\python.exe -m pytest -q`
2. Copy these changes into a git clone of `deepsleepisgood/life-inbox-copy`
   on a new branch. This downloaded folder is not a git repository.
3. Do **not** copy `.env` (holds the NVIDIA key), `.venv/`, or `data/`
   (databases and backups).
4. Anyone pulling the changes must run `python -m alembic upgrade head`,
   because changes 002, 005, 006, 008, 011 and 012 add migrations
   `0015_topic_hierarchy`, `0016_item_user_context`, `0017_ai_call_log`,
   `0018_five_life_areas`, `0019_task_priority_and_done`,
   `0020_task_date_changes`, `0021_date_provenance`, `0022_captain_answers`, `0023_filing_v2`, `0024_link_cards`, `0025_task_ideas`, `0026_hobbies_and_cooking`, `0027_memory`, `0028_scout`, `0029_weekly_review` and `0030_source_summary` (0018 and 0026 rename topics,
   and 0021 moves guessed dates off the calendar until confirmed: back up first). Upgrade the
   database before starting the new code: the app refuses to run on an old
   schema.
5. Replace the owner's real notes in
   `docs/design/prototype/new-ui-prototype.html` with made-up ones (build plan
   §9). Change 009 moved the prototype there, out of what the app serves.
