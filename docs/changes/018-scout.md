# 018: Scout, the catch-up helper

**Date:** 2026-11-09 · **Status:** Done, not pushed · **Part of:** Phase 5.

**Decisions:**
- **K (name):** Scout.
- **L (catch-up time):** Sunday 19:00, local time, changeable in Settings.
- **M (reason for dropping):** optional, and skippable.
- **F (✓ on past days):** yes.

## What it does

Scout sits under Captain in the right pane. Its status line shows "3 quick
questions", "Your weekly catch-up" or "All caught up", with a badge. It opens
its own page, `#/scout`. **No AI is used anywhere.**

**When Scout asks:**
- **The day after a task's date:** "It was on Sun 8 Nov. Did you do it?"
  Yesterday's comes first.
- **In the weekly catch-up** (Sunday 19:00 by default), the past-date tasks
  plus:
  - undated tasks waiting 14+ days: "Waiting 20 days without a date. Still
    want to do it?";
  - Someday tasks untouched for 30+ days, asked once a month: "Still
    someday?".
  - A new account waits for its first catch-up.
- **After a break of 7+ days:** "You've been away 9 days. A 1-minute
  catch-up?" This stays until you finish the catch-up.

**What it looks like:**
- At most 10 questions at a time; "N more questions next time" if there are
  more.
- Kind wording: "Let's tidy up: 3 quick questions."
- **Done for now** ends the catch-up until next week.

**Answers:**

| Question | Answers |
| --- | --- |
| Was it done? | **Done** · **Not yet, new date** (the date picker) · **Drop it** · Skip |
| No date yet | **Give it a date** · **Someday** · **Drop it** · Skip |
| Still someday? | **Keep it** · **Plan it** · **Drop it** · Skip |

**What every answer does:**
- **"Drop it"** asks "Why drop it? (optional)" with three quick reasons ("Not
  needed any more", "Someone else did it", "Too much right now") or your own
  words.
- **It's recorded:** each answer is a task event, by Scout.
- **It updates short-term memory** for a week, shown in the toast: "Captain
  updated the Learning & work bot's memory: Python quiz: done."
- **Not asked again:** an answered or skipped question doesn't come back.

**Bulk actions** ("Tidy up in one go"; each asks "…? Yes, move N / Cancel"
first):
- **Move N tasks older than 30 days to Someday:** open tasks made 30+ days ago
  with no date, or a date 30+ days past.
- **Snooze N past tasks to next week:** they move to next Monday, at the same
  time.

## Someday

- **Off your dates:** a Someday task has no date, so it leaves the Calendar,
  the Timeline, reminders and Captain's "No date yet" cards.
- **In Priority:** it waits in its own **Someday** section, apart from the
  board and the backlog.
  - "Back to my list" undoes it.
  - Any undated card on the board or in the backlog has a **Someday** link.
- **Giving it a date** takes it off Someday.

## Also in this change

- **Timeline ✓ (decision F):** each past day (and today) shows ✓ for the tasks
  done that day, by the day they were done, with a count and their names for
  screen readers. The legend says "✓ Done that day".
- **"Snooze 1 day" is now "Remind me tomorrow".** It says the date stays, and
  it's hidden on tasks with a set time (meetings, appointments), where only
  Postpone makes sense. Chips read "Reminds you Tue 10 Nov".
- **Your own actions are task events too:** completing, dropping or reopening
  a task, or setting its date, records "by you".
- **Settings → "Scout's weekly catch-up":** the day and time.
- **Push:** if you turned on notifications, the weekly catch-up arrives through
  the existing dispatcher:
  - "Scout · your weekly catch-up: 2 tasks whose day has passed. A 1-minute
    catch-up?";
  - once per catch-up slot (idempotency key `scout:<user>:<day>`);
  - only when something is past due and the catch-up isn't done.
- **"Priority opens on Today plus the next 3"** was already the case (change
  011).

## API

- **`GET /api/scout`:**
  - returns `{mode: daily|weekly|away, intro, questions, total, away_days,
    catchup_due, next_catchup, drop_reasons, bulk}`;
  - it also records that you were here (for "away").
- **`POST /api/scout/{id}/answer`:**
  - takes `{action: done|reschedule|drop|someday|keep|skip, due_on?,
    due_time?, reason?}`;
  - returns `{said, scout}`;
  - 409 if already answered; 422 for an answer the question doesn't offer, or
    a reschedule without a date.
- **`POST /api/scout/finish`** and **`POST /api/scout/bulk`**
  (`{which: old_to_someday|past_to_next_week}`).
- **`POST /api/tasks/{id}/someday`:** `{someday: true|false}`.
- **Tasks gain** `someday` and `someday_since`.

## Database: migration `0028_scout`

- **`task_events`:**
  - the task, and the kind: done, rescheduled, dropped, someday, kept or
    reopened;
  - by you or Scout;
  - an optional reason;
  - the day it was on, and the day it moved to.
- **`tasks.someday` and `tasks.someday_since`.**
- **`user_settings.away_days`.**
- **Added in place** with `ALTER TABLE … ADD COLUMN`, as 0021 and 0024 do; no
  table is rebuilt.

**The owner's database:**
- trial on a copy (deleted afterwards);
- a backup to `data/life_inbox.backup-2026-11-09-pre-0028.db`;
- 0027 → 0028, counts unchanged, integrity OK;
- the server stayed healthy.

## A safety catch

The existing notification tests load the database module with no
`DATABASE_URL`, so it points at the default `data/life_inbox.db`. They never
connect, because every database function is faked.

Scout's push would have connected there (and made a settings row for a test
user). So it's worked out only from data the dispatcher already has:
- the catch-up settings now come with each user's notification row (read
  only);
- the tasks are the ones the dispatcher already loaded.

A read-only check afterwards: the owner's database has no settings rows and
only its 2 users.

## Tests

- **Full suite:** 443 passed.
- **New: `tests/test_scout.py`** (13 tests):
  - the catch-up slot with a fixed clock;
  - the day-after question (not for today or later);
  - the weekly catch-up (and a new account waiting);
  - after a break (and it staying until you finish);
  - at most 10 questions, yesterday's first;
  - stale Someday monthly, and Keep;
  - Done (the task, the event, the memory, and 409 the second time);
  - New date (422 without one) and Drop with a reason;
  - Skip, and wrong answers;
  - your own actions as events;
  - both bulk actions;
  - Someday off the calendar and Captain's cards;
  - the push through the dispatcher, once per slot, and none once done.
- **`tests/test_shell.py`:**
  - the scout view;
  - "Remind me tomorrow" (and hidden on timed tasks);
  - a Node test of `somedayTasks`, `prioritySplit` without Someday, and
    `doneByDay`.
- **Updated:** the migration head and tasks columns.
- **Browser check (throwaway server, port 8018):**
  - the weekly catch-up with all three kinds of question;
  - Done, Drop with a quick reason (focus goes to the reason box), Someday
    and Keep, each with its toast;
  - New date through the date picker, recorded by Scout with its memory line.
    This caught a bug: the marker was cleared when the picker opened. Fixed.
  - the bulk confirm (focus on Yes);
  - Priority's Someday list;
  - Timeline's ✓2 on today;
  - the Settings form;
  - "Remind me tomorrow" hidden on the timed Dentist task;
  - no console errors.
