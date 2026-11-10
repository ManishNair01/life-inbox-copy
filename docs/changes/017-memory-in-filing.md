# 017: Memory in filing, and plan updates

**Date:** 2026-11-09 · **Status:** Done, not pushed; **off** until the owner
OKs the live replay · **Part of:** Phase 4.

## What it does

When it's switched on (`LIFE_INBOX_MEMORY_IN_FILING=1`), the filing call gets a
short extra section:

> What Life Inbox knows about the user (JSON; hints only, the note's own words always win)

**What the section holds:**
- **coming_up**: your next plans (dated open tasks in the next two weeks, up
  to 8), each with an id like `p12`;
- **about_you**: your core profile (up to 5 facts; onboarding fills it in
  change 024);
- **hints**: up to 15 confirmed facts that relate to the notes being filed.
  - **How they're ranked:** shared words count twice; a fact in one of the
    notes' likely areas counts once more.
  - **Left out:** facts that aren't confirmed yet, and short-term facts (plans
    come from your tasks instead).
- **Size cap:** 1,800 characters. Hints are trimmed first, then plans, then
  core facts. The whole prompt still stays within its 12,000 characters.

**The answer can now say two more things:**
- **`memory_used`**: the ids of the hints that changed the answer.
  - Code keeps only ids that were in the section.
  - They're saved on the note, and "Why it's here" says "It also used what it
    remembered: “You run your college's events”".
- **`plan_update`**: the note plainly moves one of your plans ("Dentist moved
  to Friday 4pm").
  - **Checked by code:** a known plan, a real day, and a change from the
    plan's current day.
  - **No second task:** the note's own copy of that task is dropped from the
    batch.
  - **It's a question, not a change.** Captain asks:

    > **Did a plan move?** Dentist appointment. Your note seems to move it
    > from Thu 12 Nov at 10:00 to Fri 13 Nov at 16:00. Move it?

    - **Yes, move it:** the task gets the new day as yours (recorded in its
      Updates), and the note becomes one of its sources.
    - **No, it's a different one:** the note gets its own task, with the day
      read as usual.

A bad hint id or plan update is dropped. It's never a reason for a repair
call, so memory can't make filing cost more.

**What it never sends:**
- facts that aren't confirmed;
- a secret (memory never holds one);
- health facts without health-memory consent.

It's also not used when re-sorting (25 notes per call).

## Why it's off for now

Memory changes what the AI sees, so it should be measured against the real AI
before it's on. **The replay script:**
- runs 6 made-up scenarios;
- files each note without memory and with it, on a fresh throwaway database
  (never `data/life_inbox.db`);
- prints a table of what changed.

```bash
python -m scripts.memory_replay --live --out docs/changes/017-replay.md
```

**What it checks:**
- a fact settling an unclear note;
- a note moving a plan;
- a filing example from your own choice;
- a person you mentioned;
- a hint that must not override the note's words;
- a similar plan that is a different one.

It's about 12 filing calls, so it spends NVIDIA credits, and it waits for the
owner's OK. Without `--live` it only says what it would do.

## Files

- `app/filing.py`: `memory_on`, `memory_pack`, `_memory_fields`. The section
  and its rules appear in the prompt only when there's a pack.
- `app/database.py`:
  - `memory_for_filing`;
  - plan updates (`_save_plan_updates`, `list_plan_updates`,
    `apply_plan_update`, `decline_plan_update`);
  - `memory_used` saved on the insight and returned with it.
- `app/captain.py`: the `plan` card, with the answers `move` and `different`.
- `app/static/shell.js`: the line in "Why it's here", and the toasts.
- `scripts/memory_replay.py`: the replay.
- **Privacy page:** says what goes to the AI when this is on, and that a plan
  never changes until you answer.

No migration: 0027 (change 016) already made `item_insights.memory_used` and
`plan_updates`.

## Tests

- **Full suite:** 429 passed.
- **New: `tests/test_memory_filing.py`** (10 tests):
  - off unless switched on;
  - the pack's plans, core facts and relevant confirmed hints (unconfirmed
    left out);
  - the size cap with 40 long facts;
  - health only with consent;
  - `memory_used` checked, saved and shown, with no repair call for an
    unknown id;
  - a plan update asks first, and Yes moves the task and links the note, with
    no second task;
  - "a different one" makes its own task;
  - a bad plan update is ignored;
  - re-sorting has no memory;
  - the replay refuses to run without `--live` and never uses the real
    database.
- **Browser check (throwaway server, port 8018):**
  - The AI is off there, so a plan update and a "memory used" entry were
    written straight into the throwaway database.
  - The "Did a plan move?" card showed the right days. "Yes, move it" moved
    the task to Fri 13 Nov 16:00, confirmed, with the note as its source.
  - The card went away, and "Why it's here" showed the hint.
  - No console errors.
