# 020: Weekly review, topic proposals, bot summaries and Captain's greeting

**Date:** 2026-11-09 · **Status:** Done, not pushed · **Part of:** Phase 5.
**Decision N:** the greeting is written by AI, once a day.

## What it does

### The weekly review: one AI call per user per week

**When it runs:**
- **By the scheduler** (`python -m app.notifications.scheduler` now also runs
  the reviews that are due).
- **Or on your first visit** once 7 days have passed. A new account waits its
  first week.
- **In the background:** Home never waits for it.

**Before the call**, code:
1. expires past plans;
2. gathers your memory facts (up to 40), this week's task events (Scout's
   answers and yours, up to 20), and **note groups**: 3 or more notes in one
   area that share a word that no topic of that area has in its name or
   description (up to 3 groups).

If there's nothing to review, no call is made.

**The call:**
- merges duplicate facts and trims outdated ones, by id;
- suggests up to 3 facts for you to confirm;
- names and describes each note group.

**Code then checks:**
- every id is real;
- a suggested fact is backed by a real fact or event, is not a secret, and
  passes the health-consent gate (as any memory does);
- a proposal's name isn't like any topic you have, its parent is one of the
  area's main topics, 3 or more real notes back it, and you never said "Don't
  suggest this" to the same group;
- a bad answer gets one repair call.

**What it changes:**
- **Merged facts:** the duplicate is expired, and the kept one gains its notes
  and count.
- **Trimmed facts:** they're expired.
- **Suggested facts:** they become "not confirmed yet" facts from the weekly
  review.

### Captain's two new questions

**A new topic?**
- **The card:** "Your Money & home notes keep coming back to this. A topic
  under Home & errands for 4 notes, like “Pay the hostel mess fees”, …?"
- **Create it:** the topic is made under its parent, and the notes move in
  (except notes you placed yourself).
- **Rename:** a name box (filled in, with focus), then Create it.
- **Not now:** the proposal is set aside.
- **Don't suggest this:** that group (area + word) is never proposed again.
- **A topic is never made without you (P1).**
- **Its history is kept:** the topic page says "Suggested by the Money & home
  bot from note #1, note #2, …; approved by you on Mon 9 Nov."

**Is this right?**
- **The card:** "You live in a college hostel. From your weekly review: Life
  Inbox thinks this is true about you. Is it?"
- **Yes:** the fact is confirmed.
- **No:** the fact is deleted, and never suggested again.
- **Edit:** opens the memory page with it ready to edit.

### Area summaries

- **An area page's summary line** is now written by AI and saved with a key of
  what the area holds (its notes and their last change, its open tasks).
- **It's reused until the area changes,** then rewritten with one call in the
  background. Until then, code's line shows.
- **It never uses** a note that holds a secret.

### Captain's greeting (decision N)

- **On Home, under "Good morning":** one warm line written by AI, once per user
  per local day, saved and reused.
- **What it may mention:** your Needs you count, today's tasks and the next
  few.
- **The checks:** under 140 characters, one sentence, no links.
- **Until it exists, or without AI,** nothing extra shows. Code's summary line
  is still there.

### When no AI is used

Every call here is skipped when no AI is configured or your AI switch
(`user_settings.ai_processing`, change 025) is off. Each job runs at most once
at a time per user.

## API

- **`GET /api/captain/greeting`:**
  - returns `{text, ai}`;
  - starts the day's greeting and a due weekly review in the background.
- **`GET /api/bots/{key}/summary`:**
  - returns `{bot_key, summary, ai}`;
  - starts a rewrite in the background when the area changed.
- **Captain's cards gain the kinds** `proposal` and `fact`.
- **The resolve answers gain** `create` (with an optional name), `never`,
  `yes` and `no`.
- **Topics gain** `proposed_by`, `evidence_item_ids` and `approved_at`.

## Database: migration `0029_weekly_review`

- **`topics`:** `proposed_by`, `evidence_item_ids` and `approved_at` (plain
  `ADD COLUMN`).
- **`topic_proposals`:**
  - area, name, description, parent;
  - its notes;
  - the group's signature (`area:word`);
  - status (pending, created, declined, never), and the topic made.
- **`bot_summaries`:** one row per user and area, with its data key.
- **`greetings`:** one row per user and day.

**The owner's database:**
- trial on a copy (deleted);
- a backup to `data/life_inbox.backup-2026-11-09-pre-0029.db`;
- 0028 → 0029, counts unchanged, integrity OK;
- the server is healthy.

**What this costs on the owner's account** (the owner's AI key is set):
- 1 greeting call a day;
- 1 weekly review call a week (the first on the next visit, since the account
  is older than a week);
- 1 summary call when an area page is opened after that area changed.

## Tests

- **Full suite:** 458 passed.
- **New: `tests/test_weekly_review.py`** (8 tests):
  - one weekly review per week, with no call when there's nothing new;
  - a new account waits a week;
  - a proposal never makes a topic until you say Create (Rename tested, the
    notes move, and the history is kept);
  - "Don't suggest this" is remembered, and similar names or wrong parents are
    dropped by code;
  - merging and trimming facts;
  - suggested facts, with no secret and no unsupported guess, and Yes on the
    card;
  - summaries reused until their area changes;
  - the greeting once a day;
  - nothing runs without AI, or with the AI switch off.
- **Updated:**
  - the migration head and the topics columns;
  - the shell test knows the Rename box.
- **Browser check (throwaway server, port 8018):**
  - The AI is off there, so a proposal and a fact were written into its
    database.
  - The topic card: Rename (prefilled, with focus) → "Hostel" was created
    under Home & errands with its 4 notes, and the history line showed on its
    page.
  - The fact card's Edit opened the memory page with the fact ready to edit,
    and saving confirmed it.
  - Both cards went away when answered. No console errors.
