# 013: Captain's "Needs you" list

**Date:** 2026-11-08 · **Status:** Done, not pushed · **Build plan:** phase 3,
change 013

## Problem

- **Questions were scattered or missing.**
  - A guessed date asked once after saving.
  - Captures that couldn't be read sat in a "retry center".
  - Notes "not yet organized" or "marked for review" showed on Home as bare
    "Open" cards.
  - Nothing at all asked about a note stuck in the old catch-all, a topic with
    no life area, a time-bound task with no date, or two things booked at the
    same time.
- **Home could say "Nothing needs you" while things did.**
- **The design's principle P3 ("ask when unsure, never guess")** needs one
  place where Captain asks. 014's filing will send unsure notes there.

## Solution

### One list, on Home and in the right panel

- **Captain's card on Home shows up to 5 questions,** ranked, as cards that fill
  their row. Each card has:
  - a kind heading ("A date to check", "Couldn't read this"…);
  - the note it's about, which opens the note page;
  - the question;
  - one-tap answers.
- **"N more questions after these. Answer one and the next shows."**
- **The greeting** ("3 things need a quick answer from you") and Captain's
  badge in the right panel count the whole list.

### The kinds of card

| Kind | Example | Answers |
|---|---|---|
| A date to check | "Call mom this weekend": You wrote "this weekend": is it Sat 14 Nov? | **Check it** (opens the date question, 012) · Not now |
| Your edit moved a date | Your edit moved it from Fri 13 Nov to Fri 20 Nov. Is that right? | **Check it** · Not now |
| Two things at once | Wed 11 Nov at 19:00: "Book a table for date night" and "Prepare the Halloween stall" | **Check** (opens that week's Timeline) · Ignore |
| Couldn't read this | https://example.com/shoe-deal: The page took too long to answer. | **Retry** · Add a note · Delete (asks "Yes, delete") · Not now |
| Not filed yet | Life Inbox hasn't filed this note yet. | **File it** (1 AI call, only on your tap) · Not now |
| Which topic? | It's in the old catch-all, Personal / Reference. Which topic fits? | **Its two likeliest topics** · Other topic… (note page) · Not now |
| No date yet | "Call the plumber": It sounds like it has a day. When is it? | **Set date** (the picker) · Drop it · Not now |
| You marked this for review | Have another look when you can. | **Open** · Done |
| Which life area? | "Chess openings": Every topic belongs to one life area. | **The five areas** (a guess first, if any) · Not now |

- **"Add a note"** opens a small box on the card ("What was it? Your words are
  used to file it."). Your note is saved on the capture, which then counts as
  read, and it's filed from your words.
- **"Which topic?" choices come from code:** topics whose name or description
  words appear in the note, plus the five areas' keyword rules. They're never
  the catch-all. Once 014 files with the AI, its two best choices take over.
- **"No date yet"** is only for tasks from a note that sound tied to a day
  (call, meet, pay, book, exam, deadline…), not snoozed.
- **"Two things at once"** means two dated tasks within an hour of each other
  in the next 30 days. Two tasks from the same note don't count.

### The rules

- **Ranked by how soon they matter:** dates (soonest first) and clashes, then
  captures that couldn't be read, then notes to file or place, then undated
  tasks, reviews and topics.
- **At most one question per note (P6).** A note's next question shows once you
  answer the first. A clash counts as the question for both of its notes.
- **Answers are kept, "Not now" included,** so a card doesn't come back. If
  its situation changes, it asks again: a guess that moves to another day, a
  note that moves to another unclear topic.
- **Each user sees only their own cards.** Someone else's card id gives 404.
- **No AI calls,** except "File it" when you tap it.

### API and data

- **`GET /api/captain/needs-you`** returns `{cards, total}`. Each card has an
  id, kind, heading, title, text, the note/task/topic ids, its answers and
  their values, and the data the app needs (the day, the choices…). It shows
  the top 20 cards and the full count.
- **`POST /api/captain/needs-you/{id}/resolve` `{action, value?}`** carries out
  the answer and returns the new list:
  - `not_now`, `ignore`, `done`;
  - `drop` (dismisses the task);
  - `add_note` (your note, up to 2,000 characters);
  - `delete` (the capture);
  - `pick` (a topic offered on the card, or a life area).

  An answer the card doesn't offer gives 422; an answered or unknown card
  gives 404.
- **The other answers** (Check it, Set date, Retry, File it, Open, Other topic,
  Check) use the app's existing actions. The card simply goes once the
  situation is fixed.
- **Migration `0022_captain_answers`** adds a table with one row per answered
  card (`card_key`): the kind, the answer, and what the card asked and what
  you chose. That's what change 016 will turn into memory examples. It can't
  be undone automatically.
- **New in `app/captain.py`:** the cards, ranking and answers.
- **New in `app/database.py`:** `captain_facts()`, `record_captain_answer()`,
  `list_captain_answers()` and `add_note_to_failed_capture()`.
- **New in `app/organizer.py`:** `topic_choices()`.

### What it replaces

- **The temporary "A date waits for your OK" card** (012 follow-up), and Home's
  "N captures couldn't be read · Review" and "Not yet organized / Marked for
  review · Open" cards.
- **The v1 retry center** (Priority's folded "All notes" with the failed
  filter) still works, but the cards are now the main way to deal with failed
  captures.

## The owner's database

- **A trial upgrade on a copy first,** then a backup to
  `data/life_inbox.backup-2026-11-07-pre-0022.db`, then 0021 → 0022. All of
  this happened before any code needing it was saved.
- **Row counts unchanged:** 2 users, 21 notes, 21 insights, 21 tasks, 35
  topics, 27 analysis runs. Integrity check OK, and the server was healthy
  after its reload.

## Files changed

| File | Change |
|---|---|
| `migrations/versions/0022_captain_answers.py` | **New.** The answers table |
| `app/captain.py` | **New.** The kinds of card, ranking, one question per note, answers |
| `app/database.py` | `CaptainAnswerRecord`; `captain_facts`; recording and listing answers; a note for a failed capture |
| `app/organizer.py` | `topic_choices()`: the likeliest topics for a note, by code |
| `app/schemas.py` | `NeedsYouCard`, `NeedsYouAction`, `NeedsYouList`, `NeedsYouResolve` |
| `app/main.py` | `GET /api/captain/needs-you`, `POST /api/captain/needs-you/{id}/resolve` |
| `app/static/shell.js` | Captain's card shows the list; each answer; the note box for failed captures; Delete asks twice |
| `app/static/shell.css`, `app/templates/index.html` | Card styles; asset version `20261107_needs1` |
| `tests/test_needs_you.py` | **New.** 15 tests, including the migration |
| `tests/test_shell.py` | The Captain card's hooks |
| `tests/test_migrations.py`, `tests/test_date_provenance.py` | Head is 0022; the 0021 test upgrades to 0021 only |

## How it was tested

- **Full test suite:** 350 passed (16 new).
- **New server tests:**
  - **each kind of card** appears and goes once answered:
    - a guess confirmed;
    - a moved date;
    - Drop it;
    - Add a note, then filed;
    - Delete;
    - picking a topic;
    - File it;
    - Done;
    - picking a life area;
    - Ignore on a clash;
  - **"Not now" is kept,** and asks again when the guess moves to another day;
  - **ranking:** date, couldn't read, which topic, no date, which area;
  - **one question per note:** a note with a guess and a catch-all topic asks
    about the date first, then the topic. A clash holds back both notes'
    other questions;
  - **privacy:** another user sees nothing and can't answer your card;
  - **checks:**
    - an answer the card doesn't offer, an unknown answer or an extra field
      gives 422;
    - signed out gives 401;
  - **migration 0022:** the table, and one row per card.
- **In the browser, on a throwaway server** (offline, made-up notes):
  - 9 kinds of question appeared, ranked, with 5 shown, "4 more questions
    after these", and the badge counting all;
  - every answer worked by click:
    - Not now;
    - Add a note: the link was filed from the words, and its guessed "until
      Friday" became its next question;
    - Delete asked "Yes, delete" first;
    - a topic pick;
    - Drop it;
    - File it;
    - Ignore, after which both clashing notes' topic questions appeared;
    - a life-area pick;
    - Done;
    - Check it, which opened the date question; Yes confirmed it.
  - On a phone, the cards stack full width.
  - The only console errors were 404s for notes not filed yet. Home's "Recently
    captured" asks for their filing, which already happened before this change,
    and is handled.

## Before pushing

- **A database upgrade is needed:** `python -m alembic upgrade head` adds
  `0022_captain_answers`. Back up first.

## Known limits

- **"Which topic?" choices are keyword guesses** until 014 files with the AI.
  When code finds nothing, the card offers only "Other topic…".
- **The date reader reads "this weekend" written on a Sunday as next
  Saturday.** It's a suggestion, so it's asked about; 014's filing call
  suggests dates with today's date in hand.
- **Topic proposals and facts to confirm** join the list in change 020.
  Memory examples from the answers come in 016.
