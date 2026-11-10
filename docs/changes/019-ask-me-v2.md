# 019: Ask me v2

**Date:** 2026-11-09 · **Status:** Done, not pushed · **Part of:** Phase 5.

## What it does

Ask me now reads three kinds of evidence, says which ones it used, and never
guesses.

**Routing is code:**
- **With a lens** (an area picked in the right pane), only that area's notes,
  remembered facts and tasks are read.
- **Without one,** it reads everything. "How I answered" names the areas of the
  best-matching notes.

**Evidence:**
- **Notes:** up to 5 passages from search, including your own notes on saved
  sources.
- **What Life Inbox remembers:** confirmed facts (016) that share words with
  the question (up to 5), each with the notes it came from.
  - Facts that aren't confirmed aren't used.
  - Health facts only with consent.
- **Your tasks on the days asked about.** Code works out the days:
  - today, tomorrow, yesterday;
  - this, next or last week; the weekend;
  - a weekday ("Saturday", "last Monday");
  - this or next month;
  - a date ("2026-11-14", "14 Nov", "Nov 14").

  Open and done tasks are read, not dropped ones; a suggested date is marked
  as not confirmed.

**The answer:**
- **Nothing matches?** No AI call at all: "I couldn't find that in your notes,
  so I won't guess."
- **Otherwise, one AI call.** Every claim must cite the evidence: a note
  passage (`item-…`), a remembered fact (`m…`) or a task (`t…`).
  - **Code checks every citation id,** and every claim's.
  - **If a check fails,** one repair call names what failed ("These citation
    ids are not in the evidence…", "The claim … cites nothing from the
    evidence").
  - **If that fails too,** you get the quoted answer: the notes' own words,
    your tasks for those days, and what Life Inbox remembers, put together by
    code.
- **Without AI** (no key), the same quoted answer, so "What do I have this
  week?" works offline too. For example:

  > For this week (Mon 9 Nov – Sun 15 Nov): Dentist appointment, Tue 10 Nov
  > at 10:00; Pay the electricity bill, Fri 13 Nov (date not confirmed); …

**What the screen shows:**
- **"From what Life Inbox remembers"** and **"From your tasks",** each with
  links to their notes.
- **Suggested actions,** made by code: "Confirm Fri 13 Nov for “Pay the
  electricity bill”?" for a task whose date is only suggested. **They run
  only when you tap them.**
- **How I answered** (folded): which areas were asked (or "your lens"), which
  notes were read, how many remembered facts were used out of how many found,
  how many tasks for which days, and how many AI calls.

## API

- **`POST /api/ask`** takes `bot` (the lens). An unknown area is a 422.
- **The response keeps** `answer`, `confidence`, `citations`, `answer_kind`
  and `mode`, and adds:
  - `facts`;
  - `tasks`;
  - `claims` (each with its citation ids);
  - `suggested_actions`;
  - `how` (areas, lens, notes read, facts considered and used, tasks read,
    period, AI calls).
- **The model's answer** can now carry `claims`. The old shape (`answer`,
  `confidence`, `citation_ids`) still works.

## Files

- `app/retrieval/ask.py`:
  - `question_period`, `_fact_evidence`, `_task_evidence`, `_areas`,
    `_suggested_actions`;
  - the checks (`_check_answer`) and the prompt;
  - `build_grounded_answer(…, bot=)`.
- `app/database.py`: `bots_for_items` (the area each note is filed in).
- `app/schemas.py`: `AskFact`, `AskTask`, `AskClaim`, `AskAction`, `AskHow`.
- `app/static/app.js`: the lens is sent; facts, tasks, actions and "How I
  answered" are shown.
- `app/static/shell.js`: `LifeInboxShell.lensKey()` and `areaName()` for
  `app.js`.

No migration.

## Tests

- **Full suite:** 450 passed.
- **New: `tests/test_ask_v2.py`** (7 tests):
  - the days a question asks about (12 phrasings, with a fixed date);
  - not found means no AI call;
  - tasks for a named day as evidence, and a suggested "Confirm" that doesn't
    run by itself;
  - remembered facts as evidence, with their notes (unrelated ones left out);
  - a bad citation gets one repair, then the quoted answer;
  - a claim without a citation is repaired;
  - the lens reads only its area (and an unknown one is a 422).
- **Updated:**
  - `test_retrieval.py`: the honest "not found" wording;
  - `test_llm.py`: an unusable answer now gets one repair call (two logged
    calls).
- **Browser check (throwaway server, port 8018, AI off):**
  - "What do I have this week?" gave the task list for Mon 9 – Sun 15 Nov,
    two "Confirm…" buttons, and "How I answered: … no AI call".
  - Tapping one confirmed Fri 13 Nov, and only then.
  - With the Money & home lens, only that area was read.
  - No console errors.
