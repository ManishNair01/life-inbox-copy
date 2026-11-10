# 011a: Capture from anywhere, and hover cards

**Date:** 2026-11-07 · **Status:** Done, not pushed · **Build plan:** added after
phase 2, at the owner's request (before phase 3)

## Problem

- **Quick Capture sat at the top of every view** (design rule §2). The owner,
  after trying it:
  - on Timeline, Calendar, Priority, Dashboard and Ask me, it "takes the main
    functionality of those features";
  - in Topics and spaces, it made the screen "confusing".
- **Seeing what's inside meant clicking.** You couldn't check a topic's notes,
  or what a note says, without opening it.

## Solution

### The composer stays on Home only

- **Home keeps Quick Capture at the top,** as before. That includes an area's
  page, which is Home with an area picked.
- **Every other view starts with its own content:** Topics and spaces, the topic
  page, Timeline, Calendar, Priority, Dashboard, Ask me, search and Settings.
- **Three ways to capture from any of them,** all opening the same composer
  (note, attachments, mic) as a panel over the view:
  - **"+ New note"** in the header, next to search;
  - **the N key** (unless you're typing in a field, or a note page is open);
  - **a round "+" button** in the bottom-right corner on phones. There, the
    composer opens as a sheet from the bottom.
- **Working in the panel:**
  - Esc, × or a click outside closes it, and focus goes back to where you
    were;
  - on Home, "+ New note" and N just put the cursor in the composer.
- **After saving,** the panel closes, you stay on your view, and a message
  says "Saved. Life Inbox is filing it now." with **Open**, which opens the new
  note. This works for notes, links, PDFs, images and voice notes.
- **There is still only one composer.** It moves between docked and floating,
  so every v1 composer ID and behaviour is unchanged.

### Hover cards

- **Topics:** hovering a topic anywhere shows a small card:
  - the topic and its life area;
  - its note count, for example "3 notes, 2 in subtopics", or "No notes yet";
  - its full description and its subtopics;
  - "Built in" for defaults.

  That covers the area cards, the topic page's subtopic chips, pinned topics,
  topic chips on Home, and the note page's path.
- **Notes:** hovering a note anywhere shows:
  - its kind and the day you saved it (your own time zone);
  - your note, for a source;
  - the start of its text, up to 220 characters, shown once for a typed note;
  - "This capture couldn't be read" if it failed.

  That covers the topic page's notes, Home's rows and the Timeline's bars.
- **On the topic page,** the notes are already loaded, so their cards need no
  extra request. Elsewhere, a note is fetched once and remembered until the
  next change.
- **The card appears after a short pause** (0.35 s). It closes when you move
  away, scroll, click or press Esc.
- **Keyboard users** get the same card when they tab to a link.
- **Touch screens don't get hover cards;** tapping opens the page as before.
- **Week bars no longer use the browser's own tooltip,** so two tooltips don't
  show at once.

## Files changed

| File | Change |
|---|---|
| `app/templates/index.html` | "+ New note" in the header; the composer's id and close button; the phone "+", the backdrop, the hover card and the message (toast) |
| `app/static/shell.js` | Opening and closing the floating composer, N, the "Saved · Open" message; hover cards for topics and notes; the page records which view is showing |
| `app/static/shell_logic.js` | `noteTitle`, `topicHover`, `notePreview` |
| `app/static/shell.css` | The composer docked on Home only; the floating panel and the phone sheet; the header button and phone "+"; hover cards; the message |
| `app/static/app.js` | `notifyCaptured()`: notes, sources and voice notes report a successful save |
| `tests/test_shell.py` | 2 new tests |
| `docs/design/life-inbox-v2-design.md` | §2's composer rule updated |

## How it was tested

- **Full test suite:** 305 passed (2 new).
- **New tests:**
  - **The page:** "+ New note" (with its N shortcut) sits before search; one
    composer, with its close button; the phone "+", the backdrop, the hover card
    and the message all exist; the composer hides outside Home; all three save
    paths report the capture.
  - **The helpers,** run in Node in India's time zone:
    - the topic card's area, counts, trimmed description and subtopics
      (archived ones skipped);
    - no notes, and a topic with no area;
    - a typed note shown once, with the local saved day;
    - a long note cut to 220 characters;
    - a link's title, your note and its text;
    - a failed PDF with a bad date;
    - titles from the first line, a file name, or nothing.
- **In the browser, on the throwaway server** (offline, made-up notes), at
  1440×900 and 375×812:
  - Topics and spaces and the topic page open with no composer;
  - N on the Calendar opened the panel with the cursor in it;
  - a save closed it, showed "Saved…", and Open opened the new note;
  - topic and note hover cards appeared beside the link and closed on
    leaving and on Esc;
  - on a phone, the "+" showed away from Home and the sheet filled the width
    from the bottom;
  - Home kept its composer;
  - no sideways overflow.
- **Fixed during the check:**
  - the panel's × wrapped under the subtitle on narrow screens;
  - a long one-line note showed its text twice in its card.

## Before pushing

- **No database upgrade:** this change has no migration.

## Known limits and next steps

- **"+ Add for this day" and similar view-specific buttons** come with the date
  picker in change 012, as discussed.
- **Hover cards show what's already known.** A note's card doesn't show its
  topic or tasks; open the note for those.
