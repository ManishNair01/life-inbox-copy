# 011: Timeline, Calendar, Priority and Dashboard

**Date:** 2026-11-05 · **Status:** Done, not pushed · **Build plan:** phase 2
(the last change of the phase)

## Problem

- **Timeline showed this week only**, with no way to look further ahead.
- **Calendar dots didn't say which part of life an item belongs to.** The day's
  list sat under the grid instead of next to the day.
- **Priority was v1's attention board and task list.** There were no High,
  Medium and Low columns, and no way to change a task's priority. A change made
  in the database would also have been overwritten by the next analysis, which
  rewrites every task's priority.
- **The Dashboard was v1's cards.** It had no week summary, nothing per life
  area, and nothing that pointed things out. Its "Related items" list also
  belongs on each note's page now (change 009).

## Solution

### Decisions E and F (from the build plan)

- **E:** priorities stay High / Medium / Low, as in the prototype and today's
  data.
- **F:** ticks for completed tasks on past days come with Scout (change 018),
  once it records outcomes. This change adds the data they will need: when a
  task was done.

### Timeline

- **Week | Month switch,** with ‹ › to move and Today to come back. The title
  reads, for example, "Mon 2 Nov – Sun 8 Nov" or "November 2026".
- **The month is one line of day columns,** with a spike per task. Taller means
  High; solid means the date is confirmed, dashed that it isn't yet.
- **"Due this week" or "Due this month"** lists the tasks, each opening its note.
- **"Undated: N"** opens Priority with the backlog unfolded, where an undated task
  can get a date. The build plan says it opens Captain, but Captain's "Needs you"
  list only arrives in change 013. Until then Priority is where you can act on
  them.

### Calendar

- **Dots take their life area's colour** (Learning purple, Money amber, Health
  red, People green, Fun blue, grey for no area). They are solid when the date is
  confirmed, dashed when it still needs your OK, and faded when done.
- **Clicking a day opens its list as a pop-up** next to the day: the teammates'
  day details, unchanged inside.
  - Close it with ×, Esc, a click outside, or by changing month.
  - Focus moves into the pop-up and back to the day on close.
  - On a phone it opens as a sheet from the bottom.
- **An item's title opens its note page.** "View source note" still does too.
- **Drag to reschedule** comes later, as planned.

### Priority

- **High, Medium and Low columns.** Each card shows:
  - its life area;
  - its date (dashed if not confirmed), or **"No date · set"**, which opens a
    date picker;
  - **Why:** the AI's reason from its note;
  - **Your pick** when you chose the priority.
- **The board opens on overdue and today's tasks plus the next 3 dated ones.**
  Later, undated and snoozed tasks wait in **Backlog (N)**, folded. Catch up with
  Scout comes in change 018.
- **Drag a card to another column to change its priority.**
  - It's saved as your value: analysis keeps updating the AI's priority, but
    never overwrites yours.
  - "Back to Life Inbox's (Medium)" clears your choice.
  - Each card also has a priority picker, so it works with a keyboard or a touch
    screen, where dragging doesn't.
- **Group by area** adds area headings inside each column.
- **+ Add task** opens today's quick task form in a panel. Task messages show
  under the heading.
- **Still there, folded:**
  - **All tasks:** open, completed and dismissed, with every action;
  - **Attention board:** with the daily briefing.

### Dashboard

- **This week:** notes captured, tasks done (with the open count), and the
  busiest day.
- **Where your attention went:** notes per life area over the last 30 days, as
  bars in each area's colour. With a lens, it shows notes per topic in that area.
- **Captain noticed:** up to 3 lines, chosen in this order:
  1. overdue tasks;
  2. your busiest area;
  3. quiet areas;
  4. a growing topic;
  5. undated tasks;
  6. a quiet topic.
- **Growing and quiet topics:**
  - growing: 2 or more new notes in 2 weeks;
  - quiet: nothing new for 30 days.
- **Coming up:** the next 5 dated tasks.
- **Worked out by code, with no AI call,** in your browser's time zone, so
  "today" and "this week" are yours.
- **"More detail"** keeps v1's dashboard cards, folded. Its "Related items" list
  is removed; each note's page shows related notes instead.

### Everything follows the lens

Timeline, Calendar, the Priority board and the Dashboard all show only the
chosen area. The folded attention board and v1's dashboard cards aren't filtered
yet, and say so.

### API and data

- **Migration `0019_task_priority_and_done`** adds two columns to `tasks`:
  - `user_priority`: your priority, checked to be High, Medium or Low;
  - `completed_at`: set when a task is completed, cleared when it's reopened.
    Tasks already done get their last update time as a best guess.

  The migration uses plain `ADD COLUMN`s, so the table isn't rebuilt. It can't
  be undone automatically.
- **Task priority:** `priority` in every response is now yours when set,
  otherwise the AI's. Task responses also gain `ai_priority`, `user_priority`,
  `bot_key`, `reason` and `completed_at`.
- **The same priority is used everywhere:** the calendar, the attention board,
  and the one-hour High-priority alerts.
- **`PATCH /api/tasks/{id}`** with `{"priority": "High" | "Medium" | "Low" |
  null}` saves your priority; null goes back to the AI's.
- **Calendar events gain `bot_key`.**
- **`GET /api/dashboard/glance?bot=&tz=`:** the Dashboard's numbers from the new
  pure module `app/attention/glance.py`. An unknown area or time zone gives 422.

## Files changed

| File | Change |
|---|---|
| `migrations/versions/0019_task_priority_and_done.py` | **New.** `tasks.user_priority` (checked) and `tasks.completed_at` |
| `app/attention/glance.py` | **New.** The Dashboard's numbers and "Captain noticed", as pure functions |
| `app/database.py` | The two columns; effective priority; each task's area and reason; `set_task_priority`; `completed_at` on every completion; `glance_rows` |
| `app/main.py` | `PATCH /api/tasks/{id}`; `GET /api/dashboard/glance` |
| `app/schemas.py` | `Task` fields, `TaskPriorityUpdate`, `CalendarEvent.bot_key`, the `Glance` models |
| `app/templates/index.html` | The Calendar pop-up; Priority and Dashboard rebuilt, with v1's parts folded below |
| `app/static/shell.js` | Timeline week and month; the Calendar pop-up; the Priority board with drag, picker, dates and grouping; the Dashboard |
| `app/static/shell_logic.js` | `monthDays`, `shiftAnchor`, `prioritySplit`, `priorityColumns`, `groupByArea` |
| `app/static/shell.css` | The styles for all of the above, plus their phone layout |
| `app/static/app.js` | Calendar dots carry the area; event titles open the note; the dashboard drops "Related items" |
| `tests/test_priority_and_glance.py` | **New.** 10 tests |
| `tests/test_shell.py` | 2 new tests (page structure for 011; Timeline and Priority helpers) |
| `tests/test_migrations.py` | Head is now 0019; the tasks table has the two new columns |

## How it was tested

- **Full test suite:** 303 passed (12 new).
- **New server tests:**
  - **A drag saves your priority:** analysing again keeps it; the calendar uses
    it; null clears it.
  - **Priority rules:** bad values, extra fields, an empty body, unknown tasks
    and other users' tasks are refused.
  - **Tasks carry their area and reason.** A manual task has neither. Calendar
    events carry the area too.
  - **`completed_at` follows the status:** complete, reopen, and marking the note
    done.
  - **The Dashboard endpoint:** this week's counts and the busiest day;
    attention per area; the lens; and refusal of an unknown area or time zone.
- **New tests of the pure Dashboard functions** (made-up data, fixed "today"):
  - week boundaries, the busiest day, and attention per area;
  - growing topics (subtopics count toward their topic) and quiet topics;
  - Coming up (snoozed and overdue tasks excluded);
  - the three "Captain noticed" lines, in order;
  - the view with a lens, and the empty state;
  - local days in India, California and UTC.
- **Migration 0019** from an 0018 database:
  - the done task gets its update time; the open one stays empty;
  - a valid priority saves, and "Urgent" is refused by the check;
  - head is 0019.
- **New shell tests:**
  - **page structure:** the columns before the folded parts; the quick form in
    its panel; the Dashboard before "More detail"; the Calendar pop-up closed
    by default; "Related items" gone;
  - **helpers:** month days (February has 28); moving the anchor (31 Jan + 1
    month → 1 Feb); the board versus backlog split; the columns; grouping by
    area.
- **In the browser, on a throwaway server** (offline, port 8018, a made-up
  account with 10 made-up notes), at 1440×900 and 375×812:
  - **Timeline:** week and month, ‹ › and Today, and "Undated".
  - **Calendar:** dot colours and dashes (computed styles checked), the pop-up
    position, closing by ×, Esc and a click outside, and a title opening its
    note.
  - **Priority:**
    - a drag (the server stored High against the AI's Medium);
    - "Back to Life Inbox's", the picker, "No date · set";
    - Group by area and + Add task.
  - **Dashboard:** with and without the lens.
  - **Phone:** no sideways overflow in any of the four views.

  No app errors in the console or the server log.
- **Fixed during the check:**
  - the month chart wrapped into rows of 7 (it inherited the week's grid);
  - the busiest day used the server's UTC day instead of yours. The browser now
    sends its time zone.
  - in a stretched card, block topic links grew to fill the space.

## Before pushing

- **A database upgrade is needed:** `python -m alembic upgrade head` (adds
  `0019_task_priority_and_done`). Back up first.

## Known limits and next steps

- **"Undated: N" opens Priority, not Captain,** until change 013 gives Captain
  its list.
- **Not filtered by area yet:** the folded attention board and v1's dashboard
  cards (marked as such).
- **Tasks done before this change** count by their last update time, a best
  guess (for example, an analysis touching a done task could move its day). From
  now on, the done time is exact.
- **The board shows the next 3 dated tasks** after today's, as designed. A
  4th-soonest task sits in the backlog even if it's due tomorrow.
- **Dragging cards doesn't work on touch screens** (a browser limit). The
  picker on each card does.
