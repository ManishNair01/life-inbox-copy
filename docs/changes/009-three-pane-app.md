# 009: The three-pane app, with Home, the lens and the note page

**Date:** 2026-11-04 · **Status:** Done, not pushed · **Build plan:** phase 2

## Problem

- **One long scrolling page, where nothing links to anything** (build plan,
  the table in §2). To find a note's tasks, its topic or its calendar entry, you
  scroll to another section and look for it.
- **No way to see one life area at a time.** Change 008 added `?bot=` to the
  API, but nothing in the page used it.
- **No single place for a note.** Its text, the AI's reason, its tasks, related
  notes and its calendar preview were spread over different sections.
- **The design prototype was served by the app** from
  `app/static/prototype/`, with the owner's real notes in it.

## Solution

### Decisions B, C and D (settled before building)

- **B, the look:** the calm palette from the design (powder blue, lavender,
  soft red, serif headings, frosted cards). It is a theme:
  `data-theme="calm"` on `<html>` overrides the team's `--li-*` colour
  variables. Remove the attribute and the team's bold theme comes back.
- **C, where v1's extras go:**
  - a search box in the header, which follows the lens;
  - "All notes" (today's list, with all its filters) in Topics and spaces;
  - Export Markdown in the account menu.
- **D, several areas at once:** later. The lens picks one area. `?bot=` takes
  one key today and can take a list later without breaking anything.

### The layout

- **Header:** the wordmark, then the lens chip ("Viewing: Health ×", or
  "Showing everything"), the search box and the account menu.
- **Left panel:**
  - Home, Topics and spaces, Timeline, Calendar, Priority, Dashboard, Ask me;
  - up to 5 pinned topics;
  - you at the bottom (opens Settings).
- **Centre:** the composer from change 005 on top, with the chosen view below.
- **Right panel:** Captain, then the five life areas, each with its one-line
  status from `GET /api/bots`.
- **It fits the window:**
  - the page itself doesn't scroll; each pane scrolls on its own if it's
    longer;
  - Home's cards stretch to fill the pane, so there is no blank space under
    them.
- **Below 900 px the panes stack:**
  - the features and the areas become bars you scroll sideways;
  - then the composer and the view;
  - the note page fills the screen.
- **Addresses:**
  - every view has one: `#/home`, `#/topics`, `#/timeline`, `#/calendar`,
    `#/priority`, `#/dashboard`, `#/ask`, `#/search?q=…`, `#/settings`;
  - the lens is in `?bot=`, so a link opens the same view;
  - Back and Forward work, and each view opens at its top.

### Home

- **Captain's card:**
  - a greeting with your first name;
  - a summary written by code, such as "4 coming up. Nothing needs you.";
  - cards for what already asks for attention: captures that failed, and notes
    the dashboard marks for review. Captain's real "Needs you" list comes in
    013.
- **This week:**
  - Monday to Sunday, one bar per task due that day:
    - solid when the date is confirmed, dashed when it isn't;
    - darker for High priority;
  - Next up: the next 3 dated tasks.
- **Today's focus:**
  - at most 3 tasks: overdue and today first, by priority, then other High
    tasks;
  - snoozed tasks are skipped;
  - "N more tasks waiting" when there are more.
- **Recently captured:** the last 4 notes, each with its title on top and its
  kind and topic underneath.
- **Everything opens something:** a task or note opens its note page, a topic
  opens its notes, and each card links to its full view.

### The lens

- **Picking an area filters everything:** pick it in the right panel, or on a
  note page's breadcrumb. These follow it:
  - All notes, the topic list, the task list and the calendar;
  - Timeline, Home, the search box and the pinned topics.
- **To see everything again:** pick the area again, click × in the header, or
  click Captain.
- **With an area picked, Home becomes that area's page:**
  - its "about" line and a summary written by code (020 writes better ones);
  - its topics, with empty ones faded;
  - what to do;
  - its week;
  - "What I learned about you", which says what is coming (016 fills it).
- **Not filtered yet.** Each says so in a note, so nothing is silently
  unfiltered:
  - the Dashboard and Priority's Attention board, in 011;
  - Ask, in 019;
  - the AI-organized inbox, which 014 replaces.

### The note page

- **It opens from everywhere a note appears:** Home, the week bars, search
  results, the calendar's "View source note", and every "jump to the source
  note" in today's screens.
- **It shows:**
  - the breadcrumb (area › topic › subtopic): the area sets the lens, and a
    topic opens its notes;
  - chips for kind, priority and the first due date;
  - your own note, from change 005;
  - the source: text, link, image thumbnail or file. A capture that failed
    says so.
  - **Why it's here: the AI's reason.** If you moved the note, it says "You
    moved it here", then "Life Inbox first filed it under Study: …". So your
    choice and the AI's stay apart, as AGENTS.md requires.
  - the note's tasks, as today's task cards: complete, dismiss, snooze,
    confirm date, preview calendar;
  - related notes, from today's related-items data;
  - actions: Mark done, Move to topic (topics grouped by area, using today's
    insight endpoint) and Show in All notes.
- **Calendar previews** started anywhere show in a dock at the bottom right,
  with today's mock confirm. × closes it.
- **Esc closes the note page,** and focus goes back to where you were.

### Nothing from v1 is lost

- **Every element ID and inline handler from the v1 page is still on the
  page.** A test checks this.
- **Where each part of v1 went:**

  | v1 feature | Where it is now |
  |---|---|
  | Sign out, sign out everywhere, change password | Account menu |
  | Notifications | Settings |
  | Failure and retry center | Settings, and "Failed captures" in the account menu |
  | Ask | Ask me |
  | Tasks: add, complete, reopen, dismiss, snooze, reminders | Priority |
  | Search, filters, editing note text | All notes, in Topics and spaces |
  | Markdown export | Account menu |
  | Service worker | Unchanged |

- **New:** a Privacy link in the account menu.
- **`app.js` gets small hooks only:**
  - its lists follow the lens;
  - every successful change sends a `lifeinbox:changed` event, so the panels
    refresh;
  - "Failed captures" switches to Topics and spaces first.

### API

- **`GET /api/items?order=desc`** lists newest first (for Recently captured).
  The default stays oldest first.

### The prototype

- **Moved** from `app/static/prototype/` to
  `docs/design/prototype/new-ui-prototype.html`. The app no longer serves it,
  and a test checks that.

## Files changed

| File | Change |
|---|---|
| `app/templates/index.html` | **Rewritten** as the three-pane app. Today's sections moved into views, with every ID kept |
| `app/static/shell.js` | **New.** Routes, lens, Home, the area page, Timeline, search, the note page, the calendar dock, refresh on change |
| `app/static/shell_logic.js` | **New.** The pure logic, testable in Node: routes, lens, week, Next up, Today's focus, pinned topics, breadcrumb, the summary text |
| `app/static/shell.css` | **New.** The layout, the calm theme, and calm versions of today's components |
| `app/static/app.js` | Lists follow the lens; changes send `lifeinbox:changed`; "Failed captures" opens Topics and spaces |
| `app/main.py`, `app/database.py` | `GET /api/items?order=desc` |
| `tests/test_shell.py` | **New.** 15 tests |
| `tests/test_calendar.py` | "Today" pinned to 2 Nov 2026 (see below) |
| `docs/design/prototype/new-ui-prototype.html` | Moved out of `app/static/` |
| `AGENTS.md`, `docs/architecture.md` | The new UI files |

## How it was tested

- **Full test suite:** 280 passed (15 new).
- **New tests (`tests/test_shell.py`):**
  - the page: its landmarks, the nine views in order, the feature links, the
    composer above the views, and the script order;
  - nothing lost: every v1 ID appears once, and every v1 handler is still
    there;
  - every element `app.js` and `shell.js` look up exists;
  - the account menu has Settings, Failed captures, Export and Privacy;
    Captain's link clears the lens;
  - views are switched without assigning `location.hash` (the bug below);
  - the prototype isn't served;
  - newest-first listing;
  - the area keys match the server's;
  - the logic, run in Node:
    - routes and the lens;
    - the week runs Monday to Sunday in three time zones;
    - week bars, Next up and Today's focus;
    - pinned topics, the breadcrumb and the summary text.
- **The teammates' calendar tests had started failing on 3 Nov 2026.** They use
  fixed dates such as "dentist on 3 Nov". After that day, the date reader
  rightly reads "3 Nov" as next year. "Today" is now pinned to 2 Nov 2026
  inside their test fixture. Their code is unchanged.
- **In the browser, on a throwaway server** (offline; a made-up account with 6
  made-up notes), at 1440×900 and 375×812:
  - every view;
  - the lens on and off, through an area, a breadcrumb, × and Captain;
  - search with and without the lens;
  - the note page: Move to topic and back, confirm date, calendar preview;
  - the calendar's "View source note";
  - adding a note (Home, Captain, pinned topics and areas refreshed);
  - Failed captures, a pinned topic, the account menu, Settings and Ask;
  - Back.

  No console errors and no server errors.
- **Bugs the browser check found, all fixed:**
  - **"Failed captures" showed every note.** Switching views by assigning
    `location.hash` fires `popstate`. `app.js` reloads its lists on `popstate`,
    with the address before the filter was added. The filtered reload that
    followed was then dropped, because a load was already running. The same
    event made every view switch reload the full notes and task lists. Views
    now switch with `pushState`, and in-app links go through the shell. A test
    guards it.
  - **On a phone the page was 801 px wide,** so the phone zoomed out. The
    sideways bars widened the single column. Fixed with `minmax(0, 1fr)`.
  - **A view kept the last view's scroll position.** Each view now opens at its
    top.
  - **The note page showed the AI's reason after you moved the note,** and the
    refresh wiped "Moved to …". Now it says you moved it, and the message
    stays.
  - **Captain didn't clear the lens.** It does now.
  - Layout:
    - empty status lines made gaps;
    - the quick task form's labels sat away from their fields;
    - titles were squeezed between chips;
    - the account email wrapped mid-word;
    - on a phone, the example text ran under the character counter.
  - **Some user-facing text named change numbers** ("arrive in change 011").
    Removed.

## Before pushing

- **No database upgrade:** this change has no migration.
- **The prototype in `docs/design/prototype/` still has the owner's real
  notes.** Replace them with made-up ones before sharing or pushing (build plan
  §9).
- **The throwaway launch entry** (`updated-throwaway-8018`) lives in the
  original repo's `.claude/launch.json`. It's a local tool setting; don't push
  it.

## Known limits and next steps

- **Not filtered by area yet:** the Dashboard and Attention (011), Ask (019) and
  the AI-organized inbox (014). Each one says so in a note.
- **Topics and spaces is today's lists in one long column:** the topic form and
  list, the AI-organized inbox, then All notes. Change 010 builds the grouped
  cards and the topic page.
- **Pinned topics are your 5 busiest topics for now,** and open All notes
  filtered by that category. A note you moved to a topic by hand isn't caught
  by that filter. The topic page in 010 fixes this.
- **Still today's views until 011:**
  - Timeline shows this week only; 011 adds the month view and history.
  - Priority is today's Attention board and task list; 011 adds the High,
    Medium and Low columns.
- **Captain's "Needs you" list comes in 013.** Until then, Captain's card shows
  failed captures and the dashboard's "needs review" notes.
- **The login page and the app look different.** The teammates restyled login
  in their dark theme, and the app uses the calm one. That stays until the team
  settles decision B.
- **Google Fonts:** `styles.css` and `login.css` load fonts from Google on
  every page view, so Google sees each visitor's internet address. The privacy
  page doesn't say so. Before beta, either serve the fonts from the app or add
  this to the privacy page. This was there before this change, and nothing
  here changes it.
