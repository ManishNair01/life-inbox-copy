# 010: Topics and spaces, and the topic page

**Date:** 2026-11-05 · **Status:** Done, not pushed · **Build plan:** phase 2

## Problem

- **Topics and spaces was v1's flat list.** 16 topics in one long column, in
  name order, with no life areas. The new topic form sat above it, and the
  AI-organized view and All notes were below.
- **No page for a topic.** A pinned topic opened All notes filtered by the
  topic's name (change 009's stopgap). That missed notes you had moved there
  by hand, and gave no way to rename, move or delete the topic.
- **New topics never showed their life area.** Change 008 made the suggestion
  return an area, but the form didn't show it, so you couldn't see or change
  where the topic would go.
- **Renaming allowed duplicates.** `PATCH /api/topics/{id}` accepted a name you
  already used. It also left the old name on the topic's notes and in the
  saved AI-organized view, so filters stopped matching.

## Solution

### Topics and spaces

- **One card per life area, busiest area first,** packed into columns so no
  column ends in a long gap:
  - each card lists its topics, busiest first, with their subtopics (↳) and
    counts;
  - empty topics are faded;
  - clicking any topic opens its page.
- **A dashed "Add your own topic" card** goes last and fills the shortest
  column.
- **"Not in an area yet"** appears only when a topic with no area holds notes,
  or when one of them is yours (so you can move it). The empty v1 catch-all on
  its own gets no card.
- **With an area picked (the lens),** only that area's card shows.
- **The summary line** reads, for example, "9 notes in 17 topics · busiest
  areas first".
- **Below the cards:**
  - All notes, with today's filters (decision C);
  - the AI-organized inbox, folded away until change 014 replaces it.

### + New topic

- **A panel opens** with the name and description form (change 002).
- **Next shows a suggestion step every time**, now with the life area:
  - **If a parent topic fits:** "“Board games” looks like part of Friends &
    partner. Make it a subtopic of Friends & partner?" You can accept, or keep
    it separate in the area shown, which you can change.
  - **If no parent fits:** "Which part of life is “Chess openings” about?",
    with the area pre-picked when Life Inbox has a guess, and one Create topic
    button.
- **The suggestion is still one call:** the same single AI call as before, or
  the keyword rules when offline (changes 002 and 008).
- **A subtopic always shares its parent's area.** "Let Life Inbox choose"
  leaves the area to the server's keyword rules.
- **The status says where the topic went:** "Added “Board games” to Fun &
  interests. Matching notes have been moved in."

### The topic page (`#/topic/<id>`)

- **What it shows:**
  - "← All topics";
  - the path (area › parent): the area sets the lens, and the parent opens its
    page;
  - the name, with "Built in" for defaults;
  - the description and the note count;
  - subtopic chips, each opening its own page.
- **Notes:**
  - newest first, 30 at a time, with Show more;
  - each opens the note page;
  - a main topic includes its subtopics' notes, matching the prototype and the
    counts.
- **Kind filters** ("All · 3", "Notes · 2", "Images · 1") appear when the topic
  has more than one kind.
- **Actions:**
  - **Rename or edit description.** A duplicate name is refused: "You already
    have a topic called “Study”." The form stays open.
  - **Life area:** moves a topic of yours, with its subtopics. Defaults stay in
    their area and subtopics move with their parent, and the page says so. A
    topic with no area shows "Choose an area".
  - **Delete:** change 003's flow, restyled. The same "Are you sure?" text says
    where the notes will go, then you land on Topics and spaces with the
    summary: "Deleted “Python”. 1 note moved to Study."
- **Every topic link now opens this page:** pinned topics, the area page's
  topics, topic chips on Home, and the note page's path.

### API

- **`GET /api/items?topic_id=N`:**
  - lists the notes filed in topic N or its subtopics, by your choice or else
    the AI's (the same rule as the lens);
  - works with `item_type`, `order` and paging;
  - someone else's topic gives 404.
- **`GET /api/topics/{id}`:** the topic with its counts, plus `type_counts`
  (its notes by kind, subtopics included). Unknown or not yours gives 404.
- **Renaming (`PATCH /api/topics/{id}` with `name`):**
  - refuses a name you already use (any case) with 400;
  - a case-only change is allowed;
  - in the same transaction, it also renames what stores the old name: your
    notes' category and the bucket names in your saved analyses. Other people's
    data isn't touched.

### Code

- **`app.js`:**
  - the flat topic list (`loadTopics`' drawing, `askDeleteTopic`,
    `deleteTopic`) is gone;
  - `loadTopics()` now asks the shell to redraw;
  - the delete wording (`topicDeletePreview`, `topicDeleteSummary`) is kept and
    reused by the topic page.
- **`shell_logic.js`:** gains the topic route, `topicGroups()` (grouping and
  order) and `typeFilters()`.

## Files changed

| File | Change |
|---|---|
| `app/database.py` | Topic filter (`_topic_item_ids`), `owns_topic`, `get_topic_detail` (with `type_counts`); rename refuses duplicates and renames categories and saved-analysis buckets |
| `app/main.py` | `GET /api/topics/{id}`; `topic_id` on `GET /api/items` |
| `app/schemas.py` | `TopicDetail` |
| `app/templates/index.html` | Topics view rebuilt (header, new topic panel with the area step, `topicGroups`, All notes, the folded AI-organized inbox); new `topic` view; the flat `#topics` list removed |
| `app/static/shell.js` | Topics and spaces cards and their packing; the new topic panel; the topic page with filters, rename, move and delete; topic links open the page |
| `app/static/shell_logic.js` | `#/topic/<id>` routes, `topicGroups`, `typeFilters` |
| `app/static/shell.css` | Masonry, the ghost card, the folded panel, the topic page |
| `app/static/app.js` | The flat topic list removed; the area step in the new topic flow |
| `tests/test_topic_page.py` | **New.** 8 API tests |
| `tests/test_shell.py` | Page structure for 010, area choices match the server, routes, grouping and filters (3 new, 3 updated) |

## How it was tested

- **Full test suite:** 291 passed (11 new).
- **New API tests (`tests/test_topic_page.py`):**
  - a topic's notes include its subtopics';
  - your move decides the topic;
  - the filter works with kind, order and paging;
  - another user's topic gives 404 on both routes;
  - the topic detail counts notes by kind;
  - rename refuses duplicates, and allows a case change and the same name;
  - rename moves categories and saved-analysis buckets to the new name;
  - rename leaves another account's data alone.
- **Mutation check:** with the rename bookkeeping switched off, the rename test
  failed. Restored.
- **New and updated shell tests:**
  - the views list includes `topic`;
  - the Topics view's order (cards, All notes, then the folded AI view);
  - the flat list is gone;
  - the new topic panel holds the form and the area step;
  - the area choices match `GET /api/bots`;
  - topic routes, including bad ids;
  - grouping and order, including the catch-all rule and the lens;
  - kind filters.
- **In the browser, on a throwaway server** (offline, port 8018, a made-up
  account with 8 made-up notes and a drawn test image), at 1440×900 and
  375×812:
  - **Topics and spaces:** cards packed into 3 columns on desktop and 1 on a
    phone, with no sideways overflow;
  - **the topic pages:** Study (built in), Python (subtopic) and Chess
    openings (no area);
  - **rename**, including the duplicate refusal;
  - **move to an area**, from "Choose an area";
  - **delete**, both a subtopic with a note and an empty main topic;
  - **+ New topic**, with a parent suggestion and a changed area, and with no
    parent;
  - **kind filters**, the lens, and every topic link.

  No new console errors: the only ones were the deliberate duplicate-name 400
  and a 404 from a check I ran. No server errors.
- **Fixed during the check:**
  - dates showed the UTC day: a note saved at 00:30 in India showed the day
    before. They now use the local day.
  - the area picker showed "Learning & work" for a topic with no area. It now
    shows "Choose an area".
  - old messages lingered when starting a new action.

## Before pushing

- **No database upgrade:** this change has no migration.

## Known limits and next steps

- **Topic ids can be reused.** SQLite gives a new topic the id of the
  last-deleted one, so an old `#/topic/<id>` link can open a different topic.
  The topics table works like this already; worth fixing if topic links are
  ever shared.
- **Kinds come from the type of capture.** A link saved with your own note
  counts as a link.
- **Offline, a new topic's description can pull in notes it shouldn't.** The
  keyword rules re-sort every note after you add a topic (change 002's
  behaviour). In the check, "Games to play with friends on weekends" pulled in
  "Call mom this weekend". With AI on, filing uses meaning instead. Change 014
  rewrites the rules.
- **Pinned topics are still your busiest five,** not ones you choose. The
  design doesn't ask for manual pinning.
