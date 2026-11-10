# 012 (part 2): Where each date came from, the small calendar, and asking right after saving

**Date:** 2026-11-07 · **Status:** Done, not pushed · **Build plan:** phase 3,
change 012 (the rest)

## Problem

- **Every date the app read went straight onto the calendar, even a guess.**
  "Call mom this weekend" became Sat 7 Nov and "Renew the insurance by Friday"
  became Fri 13 Nov, with reminders, exactly like "Dentist on 12 Nov".
- **You couldn't tell a day your words named from one the app guessed.** The
  owner asked "Why my captain is not working on confirming dates?": nothing
  asked about a guess when it was made, and "Confirm" only sat on the old task
  cards.
- **Dates were read from the day the note was filed, not the day it was
  written.** A note filed again later (Analyze Entire Inbox, or the re-sort
  after a new topic) could have its "tomorrow" move.
- **The rest of the build plan's 012 was still open:**
  - the month-grid picker;
  - "Coming Saturday → Sat 7 Nov? Confirm · Change" right after saving;
  - three chip styles;
  - a near date raising priority.

## Solution

### Three kinds of date

| Kind | When | Where it goes | Chip |
|---|---|---|---|
| **From your note** | Your words name the day: today, tomorrow, "in 3 days", "12 Nov", "Nov 12", 2026-11-12 | Calendar, Timeline, Priority, reminders | Solid: "Thu 12 Nov · 10:30" |
| **Suggested** | A guess: "this weekend", "by Friday", "next Tuesday", "in December", "asap" | Waits for your OK. **Not on the Calendar, no reminders.** Timeline and Priority show it on its day, dashed | Dashed: "Sat 7 Nov? · confirm" |
| **Confirmed by you** | You picked or confirmed it | Everywhere | Green with ✓: "✓ Fri 13 Nov" |

- **A task with no date** shows "No date · set" where a chip is shown.
- **Hovering a chip says where its date came from,** for example "From your
  note · click to change" or "Suggested from your words, not on your calendar
  yet · click to confirm or change".
- **An area's status line** in the right pane ends with "?" when its next task
  is only a suggestion.
- **Old task cards** (Priority's folded "All tasks") read "(from your note)",
  "(confirmed)" or "(suggested, confirm it)". "Confirm date" shows only for a
  suggestion.

### Asked right after saving

- **When a note you just saved has been filed,** each guessed date gets a
  question you can't miss: a card in the middle of a dimmed page (see the
  follow-up below).
  - **"Is this the right day?"** shows the day as a calendar page (NOV · 8 ·
    Sunday), the task, and "You wrote “this Sunday”."
  - **Yes, Sun 8 Nov** saves it as yours; **Pick another day** opens the small
    calendar in its place; **Ask me later** leaves it waiting.
  - **A named day just tells you:** "Added for Thu 12 Nov at 10:30. · Change".
- **Only for notes saved in this window,** not for Analyze Entire Inbox.
- **The quoted words are kept short** (60 characters). Without AI, the date
  words can be the whole sentence, so the card says "Read from your note."

### The small calendar

- **A month, Monday first,** with ‹ › to move between months.
  - The suggested day has a dashed ring ("suggested day").
  - Today is bold, and the day you pick is filled.
- **For a suggestion, a big "Confirm Sat 7 Nov" comes first.**
- **The one-click choices from part 1 stay:** "A day later / A week later", or
  "Tomorrow / Next week".
- **"Add a time · otherwise all day".** With a time, "All day" removes it again.
- **"Save Fri 13 Nov" and Cancel.** Esc closes it, and the arrow keys move the
  day.
- **Where it opens:**
  - next to the chip you clicked;
  - in the middle of the window when it opens from a question;
  - as a sheet from the bottom on phones.

### Dates are read from the day you wrote the note, in your time zone

- **"Tomorrow" means the day after you wrote the note,** or last edited it,
  however late it's filed or filed again.
- **It uses `LIFE_INBOX_TIMEZONE`** (the owner's install: Asia/Kolkata). A note
  written at 01:00 on Sun 8 Nov in India reads "tomorrow" as Mon 9 Nov.

### A near date raises a task on the Priority board

- **Due today, tomorrow or overdue, on a real date,** a task moves one step up
  (Low → Medium → High) with a "↑ Due soon" mark.
- **Only the board changes.** Your own priority (a drag or the menu) is never
  changed, and the AI's stored priority stays as it was.

### Reminders follow real dates only

- **The morning digest lists only days your note named or you set.** A
  suggestion counts among the "unscheduled tasks to review".
- **Once you confirm it with a time,** the one-hour alert for a High task works
  as before.

### API and data

- **Migration `0021_date_provenance`:**
  - adds `tasks.suggested_due_on` and `tasks.suggested_due_time`;
  - `tasks.due_confidence` is now `from_note`, `suggested`, `user_confirmed` or
    empty.
  - **Existing tasks are sorted once:**
    - confirmed → `user_confirmed`;
    - a date with high confidence, or words that name the day → `from_note`;
    - any other date → `suggested`. Its date moves into `suggested_*`, so it
      leaves the calendar until confirmed;
    - no date → empty.
  - It can't be undone automatically.
- **Tasks in the API** carry `suggested_due_on` and `suggested_due_time`.
- **`POST /api/tasks/{id}/date`** with the suggested day records "You confirmed
  …"; any other day records "Date set: …".
- **`POST /api/tasks/{id}/confirm-timing`** with no text, or with the task's own
  words, confirms its date or suggestion.
- **`GET /api/bots`**: `next_task.suggested` says the next date is only a
  suggestion.
- **The calendar's `needs_confirmation`** is kept for compatibility. It's never
  true now, because suggestions aren't listed.

## The owner's database

- **Done before the new code was saved,** so the running server never met an
  old schema:
  - a trial upgrade on a copy first;
  - a backup to `data/life_inbox.backup-2026-11-07-pre-0021.db`;
  - the upgrade from 0020 to 0021.
- **Row counts unchanged:** 2 users, 16 notes, 16 insights, 14 tasks, 35
  topics, 22 analysis runs. Integrity check OK, and the server was healthy after
  its reload.
- **The owner's 7 open tasks now:**
  - 3 confirmed by you;
  - 1 from your note;
  - 2 without a date;
  - **1 suggested** (Sat 7 Nov). It's off the calendar until you confirm it:
    look for its dashed chip.

## Files changed

| File | Change |
|---|---|
| `app/attention/dates.py` | `ParsedTiming.explicit`; `date_source()` says "from your note" or "suggested" |
| `migrations/versions/0021_date_provenance.py` | **New.** The suggestion columns, and sorts existing dates |
| `app/database.py` | The three kinds of date; dates read from the day the note was written; confirming a suggestion; the area status "?" |
| `app/schemas.py` | `suggested_due_on`, `suggested_due_time`; `BotNextTask.suggested` |
| `app/static/shell_logic.js` | `dateState`, `taskDay`, `boardPriority`, `monthGrid`, `dayParts`, `waitingDates`; `clip` exported; week spikes, Next up and Today's focus place a suggestion on its day |
| `app/static/shell.js` | Three chip styles with hover text; the month-grid picker and where it opens; the date question card and its queue; Captain's "A date waits for your OK"; Timeline legend; "↑ Due soon" on Priority |
| `app/static/app.js` | Task cards say where a date came from; "Confirm date" only for a suggestion |
| `app/static/shell.css` | Chip styles, the month grid, the picker, the question card and its dimmed page |
| `app/templates/index.html` | The dimmed page behind a question; Timeline and Calendar wording; asset version `20261107_dates8` |
| `tests/test_date_provenance.py` | **New.** 13 tests, including the migration |
| `tests/test_shell.py` | The new helpers in three time zones; chips, the question card, the typing guard and the picker's placement |
| `tests/test_calendar.py` | Pins the day the notes were written; a guess now stays off the calendar until confirmed |
| `tests/test_migrations.py`, `tests/test_task_dates.py` | Head is 0021; the 0020 test upgrades to 0020 only |

## How it was tested

- **Full test suite:** 334 passed (18 new).
- **New server tests:**
  - **Named days go straight on** ("on 12 Nov", "tomorrow", "in 3 days"): from
    your note and on the calendar.
  - **Guesses wait** ("this weekend", "by Friday", "in December", "asap"):
    suggested and off the calendar.
  - **Confirming** from the picker and from a task card puts the guess on the
    calendar as yours, recorded as "You confirmed".
  - **The area status** shows "?" for a suggestion.
  - **"Tomorrow" is read from the day you wrote the note,** even when it's filed
    three days later.
  - **No day shift in India time:** written at 01:00 on Sun 8 Nov in India,
    "tomorrow" is Mon 9 Nov.
  - **Reminders:** the digest lists the named day but not the guess. After you
    confirm the guess with a time and make it High, its one-hour alert fires at
    that time.
  - **Migration 0021** from a 0020 database sorts six kinds of existing task
    correctly.
- **New front-end tests**, run in India, Los Angeles and UTC time:
  - the three date states, and the day a task sits on;
  - the due-soon raise, which never overrides your pick or a guess;
  - the month grid for November 2026 and February 2027;
  - the chip hover text, the question after saving, and where the picker opens;
  - the calendar-page parts (including 29 Feb 2028) and which dates wait for
    your OK, soonest first.
- **Mutation check:** with "every date counts as from your note", 7 of the new
  tests failed. The rule was changed inside the test run only, never in the
  files, because the owner's server reloads on file changes.
- **Older tests adjusted:**
  - **The calendar tests** pinned "today" to 2 Nov. Since dates are now read
    from the day a note was written, they pin that day too.
  - **The "next Friday" calendar test** now expects the guess off the calendar
    until confirmed.
- **In the browser, on a throwaway server** (offline, made-up notes):
  - **Home:** a dashed "Sat 7 Nov? · confirm" chip, and a dashed bar in the week
    chart. The Calendar showed only real dates.
  - **The picker:** opened from the chip on the suggested day; Sun 8 and 11:00
    picked, then saved. The chip turned "✓ Sun 8 Nov · 11:00", the Updates said
    "Date set: Sun 8 Nov at 11:00", and the area status followed.
  - **The question after saving:** "Book the train tickets to Pune next Monday"
    → "Mon 16 Nov? · Confirm · Change". A second note's Change opened the
    picker in the middle of the window; 13 Nov was saved.
  - **Timeline:** all three chip styles in one week. Confirm turned the dashed
    bar solid and recorded "You confirmed Fri 13 Nov".
  - **Priority:** "Call mom" (Medium, due tomorrow) showed in High with "↑ Due
    soon".
  - **Phone width:** the picker opened as a bottom sheet, and Esc closed it.
  - No console errors.
- **Fixed during the browser check:**
  - The picker opened from a question spread across the whole window on a wide
    screen. It now opens in the middle; phones keep the bottom sheet.
  - Chips had no hover text.
  - Long date words made the question very long.
  - The Timeline and Calendar descriptions still described the old rule.

## Follow-up: a question you can't miss

- **What the owner said:** the question at the bottom ("“this Sunday” → Sun 8
  Nov? · Confirm · Change") "appears but it's easily ignored by my human eye".
  They asked for a more visible confirmation.
- **Now it's a card in the middle of a dimmed, blurred page:**
  - a purple band: **"Is this the right day?"**, or **"Your edit moved a
    date"** after an edit;
  - the day as a calendar page: a red month band, a big number, the weekday;
  - the task, the words the date came from, and "It goes on your calendar once
    you say yes";
  - a big **Yes, Sun 8 Nov** button, then **Pick another day** and **Ask me
    later**.
- **It opens on its own** once the note is filed, and on a phone it rises from
  the bottom.
- **Several dates take turns:** each guessed date in a note gets its own
  question ("One more date to check after this"). That includes a note with
  two guesses, which used to get only one question.
- **Edits use the same card** ("Your edit moved it from Fri 13 Nov to Fri 20
  Nov"), instead of the strip at the bottom.
- **A date you leave for later isn't forgotten.** Captain's card on Home shows
  "A date waits for your OK · Check it" (or "3 dates wait…"), the greeting
  counts it ("1 thing needs a quick answer from you"), and Captain's badge in
  the right pane shows the number. It used to say "Nothing needs you" while a
  date was waiting.
- **It can't answer for you by accident:**
  - if you're typing when it appears, it doesn't put Yes under your fingers.
    Enter and Space do nothing, and Tab reaches the buttons;
  - Esc, "Ask me later" or a click on the dimmed page closes it, and your
    half-typed note stays as it was;
  - Tab and Shift+Tab stay inside the card.
- **Tested in the browser** on the throwaway server (offline, made-up notes):
  - a saved note's guess opened the card;
  - Yes saved it and the next waiting date followed;
  - Pick another day, the arrow keys and Save picked 9 Nov;
  - the edit question confirmed a moved date;
  - a two-guess note asked twice;
  - "Ask me later" left them in Captain's card;
  - the typing guard, the focus trap, a click on the dimmed page, and the phone
    sheet;
  - no console errors.

## Before pushing

- **A database upgrade is needed:** `python -m alembic upgrade head` adds
  `0021_date_provenance`. Back up first. It moves guessed dates off the
  calendar until they're confirmed.

## Known limits

- **"Next Monday" said on a Saturday** is read as the Monday after the coming
  one (on Sat 7 Nov, Mon 16 Nov). That was already the date reader's behaviour,
  and it's why "next …" is a suggestion and gets asked about. The filing call
  (014) will suggest dates better.
- **Captain's card on Home** lists dates waiting for your OK for now. The full
  "Needs you" list (013) will take this over, with dates your edit moved.
- **After "Yes", the next question replaces the "Confirmed …" message.** The
  date's chip and the Calendar show it went through.
- **The old "All tasks" list** shows a date you set as plain text, for example
  "2026-11-13 (confirmed)". The chips elsewhere read "Fri 13 Nov".
- **Without AI, "today at 15:00" keeps "today" but loses "15:00".** This was
  already so, and only happens offline. The AI's date words normally include
  the time.
