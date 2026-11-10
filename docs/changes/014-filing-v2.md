# 014: Filing v2, one checked AI call per note

**Date:** 2026-11-08 · **Status:** Done, not pushed · **Build plan:** phase 3,
change 014 · **Decision G:** yes (notes saved together share a call, up to 5)

## Problem

- **The AI had to pick a topic even when it wasn't sure.** Unclear notes went
  to the catch-all "Personal / Reference", or got a wrong guess, and you were
  never asked.
- **Its answer was only loosely checked.** Change 004 had to fix the AI
  inventing near-duplicate topics. A bucket name it made up still became a new
  topic.
- **It copied date words, and the date reader guessed the day.**
- **"Analyze Entire Inbox" sent every note in one call.** That was large and
  costly, and it could reshuffle things.
- **Creating a topic re-filed the whole inbox.** A voice note took 3 calls. "Why
  it's here" didn't say which rule decided or who filed the note.

## Solution

### How a note is filed now (the grounding ladder, design section 4.2)

1. **Code first, for free:**
   - the rules R1–R6 in order, with keywords;
   - similar notes you filed before, found by search;
   - your topics' words, which pick the 1–2 likely life areas.
2. **One AI call.** It gets:
   - the rules R1–R6 word for word, plus "a date never decides the category";
   - today's date and your time zone;
   - the five areas and their topics, with full descriptions for the likely
     areas and names only for the rest;
   - your words, kept apart from the source (your words up to 2,000
     characters, a source up to 1,500);
   - up to 3 similar notes, each marked "by you" or "by AI".

   The whole prompt stays within about 3,000 tokens.
3. **Code checks the answer:**
   - the topic exists and belongs to that area;
   - every date is a real date and every time a real time;
   - the answer covers exactly these notes.

   A topic name with quotes or its description pasted on ("“Recipes”",
   "Skills & projects: Self-directed…") is understood without another call.
4. **One repair call if a check fails.** It names the failure ("topic
   "Statistics" doesn't exist; pick one from the list"). If that fails too, the
   offline matcher files the note.
5. **Unsure?** If the AI says so (rule R6, low confidence) or nothing fits, the
   note gets no topic. It waits in Captain's "Needs you" list with its two
   likeliest topics (013), and your pick files it.

### There is no catch-all any more

- **New accounts don't get "Personal / Reference"** (15 topics, not 16).
- **Nothing new is ever filed there.** A note no topic fits waits for you, and
  Recently captured shows it as "Waiting for you".
- **An older account's catch-all is re-sorted by "Re-sort everything",** and is
  removed once it's empty. Its notes that still don't fit wait in Needs you.
- **Deleting a main topic** re-homes its notes with the same rules. A note
  nothing fits waits in Needs you instead of going to the catch-all.

### "Re-sort everything" replaces "Analyze Entire Inbox"

- **25 notes per call, only when you click,** and it says the cost first:
  "Re-sorting 40 notes uses 2 AI calls (25 notes per call). Notes you filed
  yourself stay where they are. Click again to start."
- **Notes you filed yourself are never re-sorted.**

### A new topic re-checks only the notes that fit it

- **After you create a topic,** code picks the notes whose words fit it, at
  most 25. That's 0 calls when none fit, otherwise 1.
- **Only those that now belong in it move:** "Moved 2 notes into Python ·
  Undo". Undo puts them back.
- **A note fits a topic by a word of its name, or at least two words of its
  description,** so "Learning the Python language" doesn't pull in every note
  about learning.

### What filing records ("Why it's here")

- **The reason, the rule and who filed it,** for example: "Anything medical
  goes to Health: it mentions “crocin”." · "Rule R1 · Filed without AI · high
  confidence".
- **A note waiting for you** reads: "Life Inbox wasn't sure where this goes, so
  it doesn't guess: Captain asks you in “Needs you”."
- **"What the AI added"** on the note page, marked as AI output and kept apart
  from your words and the source (AGENTS.md):
  - for a source, a two-sentence summary and a next step ("Watch later", "Try
    this recipe");
  - for a voice note, the tidied transcript.

### Voice notes take 2 calls, not 3

- **Speech-to-text, then filing,** which also tidies the transcript. The
  separate clean-up call is gone.
- **The raw transcript stays as the note's text:** your words, as heard.

### Dates

- **Filing suggests the day for a guess** ("this weekend", "by Friday") with
  today's date in hand. It's still a suggestion that waits for your OK (012).
  A day your words name is always read by code.
- **The date reader now understands a day of the month without the month:**
  "by 5th", "before the 15th", "on the 3rd". It takes the next date with that
  day number, as a suggestion. It only does this after such a word, so "3rd
  floor" isn't a date.

### Tasks come only from your own words

- **Your own words are** a note's text, a voice note's transcript, or your note
  on a link, PDF or image.
- **A date inside a source** (an article, a screenshot) no longer creates a
  task by itself. Say it in your note ("My flight is on 18 Nov") and it does.

### The offline matcher, rewritten for the five areas

- **The rules in order,** with your own words read first (R3).
- **Pets go to the household,** not Health. **App and startup ideas** aren't
  bills.
- **Your own topics come before the default subjects,** and your subtopic wins
  inside its topic ("Refill my medicines" → Medicines & doctors › Pill
  reminder).
- **No catch-all:** unclear notes wait in Needs you.

### Batching (decision G)

- **Notes saved while a filing call runs** wait and go together in the next
  call, up to 5. The first note is never delayed.
- **This works within one server process.** A deployment with several worker
  processes batches per process.

### API and data

- **`POST /api/analyze?item_id=`** files a note through the ladder.
  **`POST /api/analyze`** without a note re-sorts everything.
- **New endpoints:**
  - `GET /api/filing/resort-plan` (notes, calls, per call, AI on or off);
  - `POST /api/filing/resort`;
  - `POST /api/topics/{id}/recheck` (the moves);
  - `POST /api/filing/undo-moves`.
- **Migration `0023_filing_v2`** adds these to `item_insights`:
  - `filing_rule`, `filing_confidence`, `filing_choices` and `filed_by`;
  - `filing_pending` (waits for your pick, no topic);
  - `ai_summary`, `suggested_action` and `cleaned_transcript`.

  Existing rows get `filed_by` from how they were filed: you, the offline
  matcher, or the AI. It can't be undone automatically.
- **The note's filing** (`GET /api/items/{id}/insight`) includes the new fields.
- **New in `app/filing.py`:** the ladder, the offline matcher, batching,
  re-sort and the new-topic re-check.

## The owner's database

- **The same order as before:** a trial on a copy, a backup to
  `data/life_inbox.backup-2026-11-08-pre-0023.db`, then 0022 → 0023. All of
  this was done before the code needing it was saved.
- **Row counts unchanged:** 2 users, 26 notes, 26 insights, 26 tasks, 36
  topics, 34 analysis runs. Integrity check OK, and the server healthy.
- **How the owner's 26 filings were recorded:** 19 offline, 3 by AI, 4 by you.
  Many earlier runs had fallen back to offline filing. The call log also shows
  voice transcription failing with "404 Not Found" from NVIDIA twice.
- **Your server now files with v2.** With your NVIDIA key it uses the new
  prompt. The live check against NVIDIA (below) hasn't been run, because it
  spends credits. If the model's answer doesn't pass code's checks, one repair
  call is made, then the offline matcher, so nothing is lost or misfiled into
  a topic that doesn't exist.

## Files changed

| File | Change |
|---|---|
| `migrations/versions/0023_filing_v2.py` | **New.** The filing columns |
| `app/filing.py` | **New.** The ladder, the prompt, code's checks, the offline matcher, batching, re-sort, the new-topic re-check |
| `app/database.py` | Filing details saved with each note; the AI's suggested day for a guess; no catch-all for new accounts; deleting a topic sends unclear notes to Needs you; re-sort, undo and catch-all helpers |
| `app/attention/dates.py` | "by 5th", "before the 15th" |
| `app/organizer.py` | Re-homing after a delete uses filing's rules and never the catch-all; `topic_choices` (013) |
| `app/captain.py` | "Which topic?" uses the filing call's two choices |
| `app/capture/voice_extract.py` | No separate clean-up call |
| `app/main.py`, `app/schemas.py` | The endpoints and the filing fields |
| `app/static/app.js` | "Re-sort everything" with its cost first; a new topic's re-check and Undo |
| `app/static/shell.js`, `app/templates/index.html` | "Why it's here" with the rule and who filed it; "What the AI added"; "Waiting for you"; asset version `20261108_filing3` |
| `tests/test_filing.py`, `tests/filing_replay.py` | **New.** 17 tests; the synthetic replay set (the research doc's 37 notes, owner's reworded, plus the design scenarios) |
| `tests/conftest.py` | The new modules reload with the database for each test |
| `tests/test_api.py`, `test_topics.py`, `test_needs_you.py`, `test_llm.py`, `test_calendar.py`, `test_life_areas.py`, `test_migrations.py`, `test_shell.py`, `test_date_provenance.py` | Follow v2. See "How it was tested" |

## How it was tested

- **Full test suite:** 368 passed (18 new; 350 before).
- **New tests (`tests/test_filing.py`, the AI always faked):**
  - **the offline matcher on the research doc's 37 notes:** 37 right. It was
    tuned against this same table, so treat that as a floor check, not real
    accuracy;
  - **the design scenarios:** right, or it asks; never a wrong guess;
  - **the rules in order:** R1 before shopping, insurance under R2, pets
    under household, a source's purpose (R3), and no tasks from a source's
    text;
  - **the prompt:**
    - every rule word for word, and "a date never decides";
    - today's date and the time zone;
    - your words apart from the source, both cut to size;
    - no catch-all;
    - 5 long notes stay under 12,000 characters;
  - **code's checks:** an invented topic, the wrong area, a duplicate, an
    unknown or missing note, a fake date and time; quotes and descriptions in
    a name are understood;
  - **one repair call** after a bad answer, which names the problem, and the
    call log shows "invalid" then "ok";
  - **the AI down:** the offline matcher files the note (R2 for rent);
  - **the AI unsure:** no topic, its two choices, and the "Which topic?" card
    offering them;
  - **dates:** the AI's suggested day for a guess, still waiting for your OK;
    a named day is read by code, even when the AI says otherwise;
  - **a source's summary and next step** are saved;
  - **batching:** a second and third note saved during a running call went
    together in the next call;
  - **calls per note:** at most 1.2;
  - **Re-sort everything:** 30 notes in 2 calls (25 + 5), each prompt under the
    cap, your own filing left alone, the cost shown first;
  - **retiring the catch-all:** a note that fits moves out, an unclear one
    waits, and the empty catch-all is removed;
  - **a new topic:**
    - only the notes that fit move, with no call when none fit;
    - Undo restores them;
    - one shared description word isn't enough;
  - **deleting a topic:** an unclear note waits in Needs you;
  - **migration 0023:** `filed_by` is set for existing filings.
- **Updated tests:**
  - **AI mocks:** the analysis tests now fake the v2 answer and check the
    same guarantees: a re-filed task keeps its status, a failed run never
    replaces the last good one, an invalid answer is never saved, and errors
    stay friendly.
  - **The AI can never invent a topic (P1).** This replaces "a new AI bucket
    creates a topic".
  - **Voice:** 2 calls, with the tidied transcript saved as AI output.
  - **Calendar:** an image's date comes from your note on it.
  - **New accounts:** 15 topics, no catch-all.
- **In the browser, on a throwaway server** (offline, made-up notes):
  - **filing by rule, each with its reason:** Python quiz → Study (R5), Crocin
    → Medicines & doctors (R1), rent → Bills (R2), Atomic Habits → Watch, read
    & listen;
  - **a note nothing fits:** "Which topic? Life Inbox wasn't sure…" offering
    Skills & projects and Study, "Waiting for you" in Recently captured, and on
    the note page "Rule R6 · Filed without AI · low confidence";
  - **creating "Python" under Study:** "Moved 2 notes into Python · Undo", and
    Undo put them back;
  - **Re-sort everything:** "uses no AI calls (offline)… Click again to
    start", then it ran;
  - no new console errors.
- **Found and fixed during the check:**
  - **Similar-note search** read a field that doesn't exist, and would have
    failed every AI filing on the owner's server. Caught by a test minutes
    after it went live; no note was affected.
  - **A topic's description word alone** pulled an unrelated waiting note into
    a new topic.
  - **The note page** said "Not filed yet" for a note waiting for your pick.

## Before pushing

- **A database upgrade is needed:** `python -m alembic upgrade head` adds
  `0023_filing_v2`. Back up first.
- **Live check, manual, a few credits:** file the synthetic notes in
  `tests/filing_replay.py` against NVIDIA, to confirm the real model's answers
  pass code's checks (build plan section 7). Not run yet: it needs your OK.

## Known limits

- **Memory isn't in the prompt yet.** That's change 017. "Talk to admin about
  the budget again" asks in Needs you until memory knows you run college
  events.
- **The offline matcher is keyword-based.** It knows only the words in its
  lists and your topics.
- **"Re-sort everything" runs in the request,** so a very large inbox makes one
  long request (25 notes per call).
- **Link cards** (the source the call sees for a link) come in change 015. Until
  then a link's source is its page text, cut to 1,500 characters.
