# 014a: Thought-to-action (ask before a maybe becomes a task)

**Date:** 2026-11-08 · **Status:** Done, not pushed · **Asked for by:** the
owner's backlog item "Thought-to-Action Engine", after this note became a task
with a date question: "…I found a Dhaba near Mathura which I want to visit when
I will travel on that route again".

## Problem

- **Filing turned every action in your words into a task.** A wish ("I want to
  visit… next time") became "Visit the Dhaba near Mathura".
- **Captain's "No date yet" card then asked for a date** ("visit" is on its
  list), though no date exists.
- **The backlog asks for the difference** between thoughts, aspirations,
  tentative plans, commitments and instructions. It wants Life Inbox to suggest
  the smallest useful next step and ask before creating a task when the intent
  isn't explicit. Example: "I should probably call Rahul about our Jaipur trip"
  should suggest a follow-up task and ask.

## Solution

| Your words | Intent | What happens |
|---|---|---|
| "Pay rent to landlord by 5th", "Call mom tomorrow" | **Commitment** or instruction | A task, straight away (as before) |
| "I should probably call Rahul about our Jaipur trip" | **Tentative** (a maybe) | No task yet. Captain asks **"Make this a task?"**: Add task · Not now |
| "…a Dhaba near Mathura which I want to visit when I travel that route again" | **Someday** (a wish, no real time) | No task, no question. It stays with the note as a **Someday** idea, with "Add as task" |
| "Interesting dhaba near Mathura" | A thought | Nothing |

- **The filing call labels each action's intent** and gives the smallest useful
  next step. Code checks the label.
- **Without AI, the words decide.** "should", "probably", "maybe", "might",
  "planning to" mean tentative. "someday", "next time", "want to visit/try/go",
  "when I travel…" mean someday.
- **Ideas aren't tasks:** they never reach the calendar, reminders, Priority or
  the "No date yet" card.
- **On the note page,** under "Ideas, not tasks yet", Maybe and Someday ideas
  each have **Add as task**. "Things you might do. They stay off your calendar
  and lists until you add them."
- **"Add task" makes a real task** on the note. Its timing is read as usual, so
  a guessed day still waits for your OK.
- **"Not now" dismisses the maybe.** Filing the note again doesn't suggest it
  again.
- **Filing a note again uses the new labels.** A task the AI first got wrong
  becomes an idea.

### API and data

- **Migration `0025_task_ideas`** adds the `task_ideas` table (the note, text,
  timing words, intent tentative/someday, status waiting/added/dismissed, the
  task it became).
- **New endpoints:** `GET /api/items/{id}/ideas` and `POST /api/ideas/{id}/add`.
- **A new Needs you card kind, `idea`,** with the answers `add` and `not_now`.
- **No extra AI calls.**

## The owner's database

- **Trial on a copy,** then a backup to
  `data/life_inbox.backup-2026-11-08-pre-0025.db`, then 0024 → 0025, before the
  code needing it was saved.
- **Row counts unchanged:** 2 users, 28 notes, 28 insights, 34 tasks, 36 topics,
  37 analysis runs. Integrity check OK.
- **The Dhaba task filed before this change stays a task until it's dealt
  with.** Either drop it ("Drop it" on its card), or file the note again
  (1 AI call), which makes it a Someday idea.

## Files changed

| File | Change |
|---|---|
| `migrations/versions/0025_task_ideas.py` | **New.** The ideas table |
| `app/filing.py` | Intent in the prompt and in code's checks; offline intent; maybes and someday ideas kept out of tasks |
| `app/database.py` | `TaskIdeaRecord`; ideas saved with each filing; add or dismiss an idea; Captain sees waiting maybes |
| `app/captain.py` | The "Make this a task?" card |
| `app/main.py`, `app/schemas.py` | The idea endpoints and types |
| `app/static/shell.js`, `app/templates/index.html` | "Ideas, not tasks yet" on the note page; asset version `20261108_ideas1` |
| `tests/test_ideas.py` | **New.** 9 tests |
| `tests/test_migrations.py` | Head is 0025 |

## How it was tested

- **Full test suite:** 388 passed (8 new; 380 before).
- **New tests:**
  - offline intent;
  - the Dhaba note: no task, a Someday idea, no question, not in the task list;
  - the Rahul note: no task, "Make this a task?", and Add task makes it;
  - Not now is final, even after filing again;
  - "Pay rent by 5th" is still a task;
  - Add as task from the note page, and only for your own ideas;
  - the AI's intent labels, and filing again turns a wrong task into an idea;
  - migration 0025.
- **In the browser, on a throwaway server** (offline, made-up notes):
  - Home's Captain card asked "Make this a task?" for the Rahul note only;
  - the Dhaba note page showed "Someday …" under "Ideas, not tasks yet";
  - no script errors.

## Known limits

- **Offline, an idea's text is the whole sentence.** With AI, it's the short
  next step.
- **Someday ideas don't surface anywhere yet** except their note. Scout's
  monthly "stale Someday items" (018) is the natural place.
