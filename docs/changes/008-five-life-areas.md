# 008: The five life areas

**Date:** 2026-11-02 · **Status:** Done, not pushed · **Build plan:** phase 1

## Problem

- **Topics have no life area.** The v2 design puts every topic under one of
  five life areas ("life bots"), but topics were a flat list.
- **The defaults are v1's nine.** That set includes a catch-all, and the
  research found it doesn't cover real notes well (design §4.1,
  `docs/research-life-categories.md`).
- **"Built-in" was decided by name.** Renaming a built-in topic made it
  deletable.
- **No way to see one area at a time.** Nothing could list or filter by area,
  which the new app's lens (change 009) needs.

## Solution

### The five areas, in code (`app/bots.py`)

| Area (key) | Default topics |
|---|---|
| Learning & work (`learn`) | Study · Work & career · Skills & projects |
| Money & home (`money`) | Bills & subscriptions · Bank, tax & documents · Home & errands |
| Health (`health`) | Medicines & doctors · Fitness & food · Mind & mood |
| People (`people`) | Family · Friends & partner · Occasions & gifts |
| Fun & interests (`fun`) | Watch, read & listen · Cooking & hobbies · Trips & places |

Each default has the research's description (§3). Each area has the "about"
text the AI reads (§6.2). The offline keyword rules now point at the new
defaults.

### Every topic knows its area and where it came from

- **Two new columns on `topics`:**
  - `bot_key`: the area, or none yet;
  - `origin`: `built_in` (a default), `user` (yours) or `ai` (invented by v1
    analysis).
- **"Built-in" now comes from `origin`,** so a renamed default stays built in
  and still can't be deleted.
- **New accounts get the 15 defaults.** They also get "Personal / Reference",
  with no area, until change 014. Today's filing still falls back to it, and
  014 re-sorts its notes and removes it.

### Moving existing accounts (migration `0018_five_life_areas`)

- **v1 topics are renamed, not replaced,** so every note stays on its topic:

  | v1 | New |
  |---|---|
  | Learning | Study |
  | Work | Work & career |
  | Money & Admin | Bills & subscriptions |
  | Shopping & Errands | Home & errands |
  | Health | Medicines & doctors |
  | Travel | Trips & places |
  | Ideas | Skills & projects |
  | People | Friends & partner |

- **The missing defaults are added.**
- **If you already have a topic with a new default's name** (say your own
  "Study"), the old one is merged into it: notes, subtopics and the stored
  analysis view all move over.
- **Descriptions you edited are kept.** Archived topics stay archived.
- **Your own topics get an area:**
  - a subtopic takes its parent's area;
  - a main topic gets one from the keyword rules, or none if nothing fits.
    Captain will ask about those (change 013).
- **Saved categories and the stored "AI-organized inbox" view are renamed to
  match.**
- **The migration can't be undone automatically.** To go back, restore the
  backup.

### API

- **`GET /api/bots`:** the five areas, each with its topic count, note count,
  open tasks, next dated task and a one-line status, such as "Read lecture
  notes · Tue 3 Nov", "1 open task, no dates" or "Nothing yet".
- **`?bot=` (the lens)** on `GET /api/items`, `/api/tasks`,
  `/api/calendar/events`, `/api/topics` and `/api/search`:
  - A note belongs to an area through its topic. Your own choice counts first,
    otherwise the AI's.
  - Tasks and calendar entries count through their source notes.
  - Search filters before ranking.
  - An unknown area gives 422.
- **Creating a topic** takes an optional `bot_key`:
  - a subtopic always shares its parent's area, and asking for a different
    one gives 400;
  - without one, the keyword rules choose.
- **`PATCH /api/topics/{id}` with `bot_key`** moves a main topic, with its
  subtopics, to another area. Built-in topics and lone subtopics can't be
  moved (400).
- **The subtopic suggestion** (`POST /api/topics/suggest-parent`) now returns
  `suggested_bot` too, from the same single AI call. A subtopic takes its
  parent's area; otherwise the AI's choice, otherwise the keyword rules.

## Files changed

| File | Change |
|---|---|
| `app/bots.py` | **New.** The five areas, default topics, descriptions, "about" text, keyword rules |
| `migrations/versions/0018_five_life_areas.py` | **New.** `bot_key` and `origin`, and the move from v1 (constants copied in, so it never changes later) |
| `app/database.py` | New columns; the 15 defaults; built-in by origin; area on create and move; v1 AI-invented topics get an area; `list_bots_from_db()`; the `?bot=` filters |
| `app/organizer.py` | Keyword rules from `app/bots.py`; the subtopic suggestion also suggests an area |
| `app/schemas.py` | `Topic.bot_key` and `origin`; `bot_key` on create and update; `suggested_bot`; `LifeBot` |
| `app/main.py` | `GET /api/bots`; `?bot=` on five lists; area validation; topic conflicts give 400 |
| `app/retrieval/search.py` | Optional note filter before ranking |
| `tests/test_life_areas.py` | **New.** 14 tests, including a full migration from a made-up v1 database |
| `tests/test_topics.py`, `test_api.py`, `test_context.py`, `test_llm.py`, `test_migrations.py` | Old topic names updated to the new ones, with what each test checks kept |
| `AGENTS.md`, `docs/architecture.md` | The new module and the topic columns |

## How it was tested

- **Full test suite:** 265 passed (14 new).
- **New tests:**
  - a new account gets 5 areas × 3 topics, plus the catch-all with no area;
  - `GET /api/bots`: order, names, counts, and the status line with the next
    dated task;
  - users only see their own counts;
  - `?bot=` works on all five lists; an unknown area gives 422;
  - your own move decides a note's area;
  - creating topics, with and without an area; a subtopic shares its parent's
    area;
  - moving rules; a renamed default stays built in;
  - the suggestion includes the area.
- **The migration test** builds a made-up v1 database, with these cases:
  - a merge into the user's own "Study";
  - an edited description that must be kept;
  - subtopics;
  - a topic invented by v1 AI;
  - the user's own "Family";
  - the stored analysis view;
  - a second account with only defaults;
  - an account with no topics yet.

  **It caught a real bug:** new defaults added by the migration were treated
  as the user's own topics in the last step, so "Bank, tax & documents"
  landed in Learning & work. Fixed: built-ins are now recognised by name.
- **Updated tests:** 29 existing tests used the v1 names and were updated.
  Four now show intended v2 behaviour:
  - "Recipes" gets the parent Cooking & hobbies;
  - "health" is no longer a topic name;
  - a re-homed recipe goes to Cooking & hobbies, not the catch-all;
  - "buy medicine for mom" still goes to Home & errands under the old keyword
    order, until rule R1 in change 014.
- **In the browser, on a throwaway server** (offline, made-up notes): today's
  screens show all 16 topics with their new descriptions and counts. Adding
  "Python" through the topic form suggested "Make it a subtopic of Study?" and
  created it there, in Learning & work. `GET /api/bots` gave the expected
  status lines. No console errors.
- **Your database**, backed up to
  `data/life_inbox.backup-2026-11-02-pre-0018.db`:
  - notes, insights, tasks and users are unchanged (12 / 12 / 9 / 2);
  - no note lost its topic;
  - Learning, Work, Money & Admin, People and Travel became Study, Work &
    career, Bills & subscriptions, Friends & partner and Trips & places, with
    the same notes;
  - Pill Reminder is under Medicines & doctors (Health), Python under Study
    (Learning & work), and Cooking Ideas is in Fun & interests.

## Before pushing

- **A database upgrade is needed:** `python -m alembic upgrade head` (adds
  `0018_five_life_areas`). It renames topics, so back up first; it can't be
  undone automatically.
- The browser check used a new launch entry, `updated-throwaway-8018`, in the
  original repo's `.claude/launch.json`. It's a local tool setting; don't push
  it.

## Known limits and next steps

- **The catch-all stays until change 014,** which re-sorts its notes and
  removes it.
- **The offline keyword rules are v1's, moved onto the new topics.** Change 014
  rewrites them in rule order R1–R6. Until then, for example, "buy medicine"
  files as an errand.
- **Your "Cooking Ideas" sits next to the new "Cooking & hobbies".** You can
  delete "Cooking Ideas", and its 3 notes will be re-sorted.
- **Nothing in today's screens shows areas yet.** The new app (009–011) shows
  them.
- **Built-in topics can't be moved to another area.** That's a choice made
  here, and easy to relax if you want it.
