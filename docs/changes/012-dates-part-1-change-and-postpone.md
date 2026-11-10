# 012 (part 1): Change any date, postpone in place, and confirm again after an edit

**Date:** 2026-11-07 · **Status:** Done, not pushed · **Build plan:** phase 3,
change 012 (first part)

## Problem

The owner's real case: "Attend Statistics meeting today" was postponed.

- **Changing the date took many clicks:** open the note, Show in All notes, edit
  the text.
- **Even then it didn't work.** That task's date had been confirmed. A confirmed
  date was locked, so editing the text changed the task's wording but not its
  date, and the Calendar and Timeline kept showing the old day.
- **Nothing in the app could change a confirmed date.**
- **The note didn't record what happened.**

The owner asked for:
- **"Postpone and set the date here itself"**;
- **the app "automatically adds points in note that the meeting is postponed on
  this particular date"**;
- **"From now even if I confirm one date on a task and later want to change the
  date it should change it"**;
- **"after confirming… if I edit the note again and change the date in text,
  the task should change the date again, and ask for reconfirmation."**

## Solution

### Change a date where you see it

- **Every task date is a button.** It opens a small date picker. You'll find
  dates on:
  - Home's rows, Timeline's lists and an area's page;
  - Priority cards and the Dashboard's "Coming up";
  - the Calendar pop-up, which now has **Postpone**;
  - task cards on a note's page, which now have **Postpone**, or **Set date**
    when there's none.
- **The picker shows the task and its current date,** for example "Now: Fri 20
  Nov · confirmed". It has:
  - **Two one-click choices, always later than now:** "A day later" and "A week
    later" for a task due later on; otherwise "Tomorrow" and "Next week".
  - **A date and an optional time,** with Save date. It also has **Confirm** when
    the date is still waiting for your OK.
- **Your date wins, even over a confirmed one.** It's saved as yours (confirmed)
  and moves everywhere: Calendar, Timeline, Priority, Dashboard, reminders.
- **A message says what happened,** for example "Postponed to Fri 27 Nov. The
  note keeps this in its updates. · Open note".

### The note keeps its history ("Updates")

- **Every date change is recorded:**
  - set;
  - postponed;
  - moved earlier;
  - confirmed;
  - moved by your edit.
- **It shows under the note** in an **Updates** list, newest first, with the
  day it happened:
  - "You confirmed Mon 30 Nov · Sat 7 Nov"
  - "Your edit moved it from Fri 27 Nov to Mon 30 Nov · Sat 7 Nov"
  - "Postponed from Fri 20 Nov to Fri 27 Nov · Sat 7 Nov"
- **It's stored apart from your note's text,** so your own words stay exactly as
  you wrote them (the AGENTS.md rule), and the AI doesn't re-read "postponed"
  as something new to file.
- **The Markdown export includes the Updates.** It now also includes your own
  note on a source, which it had been leaving out since change 005.

### Editing a note re-checks its confirmed dates

- **When you edit a note's text,** its open tasks with a confirmed date are
  marked for a re-check.
- **When the note is filed again, which happens straight after an edit:**
  - **If the new text gives a different date,** the task moves there, waits
    for your OK, and the app asks: "Your edit moved “Attend Statistics meeting…”
    to Mon 30 Nov. Is that right? · Confirm · Change · ×". The question stays
    until you answer or dismiss it.
  - **If the date is the same, or the text gives no date,** it stays confirmed
    and nothing is asked.
- **Without an edit, a confirmed date never moves.** "Analyze Entire Inbox" and
  the re-sort after a new topic leave it alone, so the AI's wording drifting
  between runs can't shift a date you confirmed.

### API and data

- **`POST /api/tasks/{id}/date` `{due_on, due_time?}`:** your date for the task,
  even over a confirmed one. A bad date or time gives 422; someone else's task
  gives 404.
- **`GET /api/items/{id}/updates`:** the note's date history, with its wording
  and whether a change still waits for your OK.
- **Migration `0020_task_date_changes`:**
  - `task_date_changes` keeps the note and the task's text, so the history
    survives if analysis replaces the task;
  - `tasks.date_recheck` marks dates to re-read after an edit.
  - It can't be undone automatically.
- **Confirming a date** is now recorded as an update too.

## What's left of change 012

- the plan's **month-grid picker** (this part uses the browser's date field);
- **"Coming Saturday → Sat 7 Nov? Confirm · Change"** right after saving a note;
- **vague dates kept off the calendar** until you confirm them;
- **chip styles** for "from your note", "suggested" and "confirmed by you";
- **a near date raising a task's priority.**

## Files changed

| File | Change |
|---|---|
| `migrations/versions/0020_task_date_changes.py` | **New.** The date history table and `tasks.date_recheck` |
| `app/database.py` | `TaskDateChangeRecord`; `set_task_date`; `list_item_updates` and the update wording; edits flag confirmed dates; analysis moves a flagged date and asks again; confirming is recorded |
| `app/main.py` | `POST /api/tasks/{id}/date`, `GET /api/items/{id}/updates`; the export adds your note and the updates |
| `app/schemas.py` | `TaskDateUpdate`, `TaskDateChange` |
| `app/static/shell.js` | Date chips as buttons; the picker; the Updates list on the note page; the question after an edit; messages with several buttons |
| `app/static/shell_logic.js` | `addDays`, `postponeChoices` |
| `app/static/app.js` | "Postpone" on the Calendar pop-up and task cards; edits and re-filing are announced |
| `app/static/shell.css`, `app/templates/index.html` | The picker and the Updates list |
| `tests/test_task_dates.py` | **New.** 8 tests, including the migration |
| `tests/test_shell.py`, `tests/test_migrations.py`, `tests/test_priority_and_glance.py` | New page and helper tests; head is now 0020 |

## How it was tested

- **Full test suite:** 315 passed (10 new).
- **New server tests:**
  - **Changing a confirmed date:** later with a time, then earlier. The
    calendar follows, and the updates read "Moved earlier…", "Postponed…" and
    "You confirmed…".
  - **An undated task given a date** ("Date set").
  - **Rules:** an impossible date, a bad time and an extra field give 422;
    unknown and other people's tasks and notes give 404.
  - **The owner's case:** confirm, edit the note to a new date, and the task
    moves and waits for your OK. The update says so, and confirming clears it.
  - **An edit that keeps the date** stays confirmed and adds nothing.
  - **Analysis without an edit** (single note and whole inbox) never moves a
    date you set.
  - **The export** has "Your note" and "Updates".
  - **Migration 0020** from a 0019 database: the table and column exist, and the
    kind check refuses unknown kinds.
- **Mutation check:** with the edit re-check switched off, the owner's-case test
  failed. Restored.
- **In the browser, on a throwaway server** (offline, made-up notes):
  - a confirmed Fri 20 Nov moved to Fri 27 Nov with one click (Priority), and
    the calendar followed;
  - the note page showed both updates, and its task card has Postpone;
  - editing the note's text to "on 30 Nov" moved it and asked "Is that
    right?"; Confirm closed the question and recorded "You confirmed Mon 30
    Nov";
  - the Calendar pop-up's Postpone opened the picker;
  - no console errors.

## Before pushing

- **A database upgrade is needed:** `python -m alembic upgrade head` (adds
  `0020_task_date_changes`). Back up first.

## Also fixed: "Snooze 1 day" uses your own day

- **Problem:** the button took "tomorrow" from a UTC date. In India, the UTC
  date is still yesterday until 05:30. Between midnight and 05:30, "Snooze 1
  day" only hid the task until later the same day: at 01:00 on Sun 8 Nov it
  snoozed "until 8 Nov".
- **Fix:** tomorrow comes from your local date (`app.js`, the task card's Snooze
  button). At 01:00 on Sun 8 Nov it now snoozes until 9 Nov. Snooze still never
  changes the task's date.
- **Kept as it is:** the owner chose to keep Snooze until Scout (change 018). The
  ideas to rename it "Remind me tomorrow" and hide it on tasks with a set time
  are noted in the build plan under 018.
- **Tested:**
  - a new test (`tests/test_shell.py`) fails if UTC day maths comes back in the
    front end (`setUTCDate`, `getUTCDate`, `toISOString().slice(0, 10)`);
  - in the browser (time zone Asia/Calcutta), Snooze set your local tomorrow and
    left the due date alone;
  - a Node check at 01:00 India time showed the old code giving the same day
    and the new code the next day.

## Known limits

- **Your real Statistics meeting task** is confirmed for 6 Nov. With this
  change you can move it from any of its date chips.
- **Only a note's own text triggers the re-check.** Editing your own note on a
  saved source (change 023) will join when that edit exists.
- **If analysis replaces a task outright** (because your edit changed what it
  says), the new task starts unconfirmed with the new date. The old confirmed
  date is then not listed as moved.
