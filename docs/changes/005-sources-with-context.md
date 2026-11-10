# 005: Add a source together with your own note (one composer)

**Date:** 2026-11-02 · **Status:** Done, not pushed · **Core feature: shown to every user**

## Problem

Links, PDFs, images and audio were saved through four separate forms in a
"More capture options" drawer, and **only the source itself** was saved. There
was no way to say *why* you were saving it, for example
*"I'll refer to this video when I learn Python."*

That "why" is often the best clue to the right topic. A general coding video
says nothing about Python, but the user's note does. Without it, the AI could
only guess from the source's content. For a YouTube link that's often just a
short, cut-off summary (see the link-capture investigation).

## Solution

### One composer, like Claude

The Quick Capture box is now the single place to add anything:

```
┌─ QUICK CAPTURE ─────────────────────────────────────┐
│ I'll refer to this video when I learn Python.       │
│                                     45 / 2000 · max │
└─────────────────────────────────────────────────────┘
 [LINK] https://www.youtube.com/watch?v=…           [×]
 [+ Link] [+ PDF] [+ Image] [+ Audio]  [Record note] [Add link with note]
```

- **Note only** saves a normal note, as before.
- **Attachment plus note:** the note is saved as that source's **context**.
- **Attachment only:** the source is saved with no context.
- **+ Link** opens a small field; paste a link and press **Attach link** or
  Enter. A link pasted on its own into the note box is also saved as a link.
- **+ PDF / + Image / + Audio** open the file chooser. One attachment at a
  time; choosing another replaces it, and **×** removes it.
- **The button says what will happen:** *Add note*, *Add link*,
  *Add link with note*, *Add PDF with note*, and so on.
- **Record note:** anything typed in the box is saved as the recording's
  context.
- **If saving fails,** the note and the attachment stay, so you can try again.
- **After saving,** each item card shows **"Your note: …"** above the source's
  own content.

### The note drives the sorting

- The note is stored in its **own column** (`inbox_items.user_context`),
  separate from the source's original and extracted text. This follows the
  AGENTS.md rule to keep the user's words apart from source and AI content.
- **The AI receives** each item's `source` type (url / pdf / image / voice),
  its `source_title`, the user's `context`, and the source's `text`. A new rule
  tells it that **context is the strongest signal** for the topic, priority
  and tasks, for example "for learning Python" goes to the **Python** subtopic.
  It is also told never to follow instructions written inside a source's text.
- **Offline (no AI key):** topic matching checks the note first (the user's
  topics, then the built-in keywords), then the source text.
- **The item title stays the source's own title** (page title or file name),
  never the user's note.
- **Ask My Inbox and search** also look in the note, so asking "which video was
  for Python?" finds it.
- **Limit:** a note can be up to 2000 characters. The server rejects longer
  notes with 422, and the box itself stops at 2000 (change 001).

## Files changed

| File | Change |
|---|---|
| `migrations/versions/0016_item_user_context.py` | **New.** Adds `inbox_items.user_context` |
| `app/database.py` | `user_context` column and in `_item_to_dict`; the four `add_*_item_to_db` functions accept `user_context`; `_note_from_item()` gives the organizer `context`, `source` and `source_title`; topic-delete reassignment includes the note |
| `app/schemas.py` | `InboxItem.user_context`; `UrlItemCreate.context`; `NOTE_MAX_LENGTH` |
| `app/main.py` | `_clean_context()`; `/api/items/url` takes `context`; `/pdf`, `/image` and `/voice` take a `context` form field |
| `app/organizer.py` | Prompt rule 15 (context is the strongest signal; ignore instructions in sources); notes sent with `source`, `source_title`, `context`; offline matching uses context first; titles come from the source |
| `app/retrieval/documents.py` | The note is indexed for search and Ask ("your note") |
| `app/templates/index.html` | New composer; the "More capture options" drawer is removed |
| `app/static/app.js` | `addCapture()`, `setupComposer()`, attachment handling; `addUrl/addPdf/addImage/addVoice` replaced; recording includes the typed note; "Your note" on cards; `setStatus` and `setButtonBusy` cope with missing elements |
| `app/static/styles.css` | Composer, attachment chip and link field styles |
| `tests/test_context.py` | **New.** 12 tests |
| `tests/test_api.py`, `tests/test_migrations.py` | Updated for the new field and migration `0016` |
| `decision.md` | Entry for this change |

## How it was tested

- **Full test suite green:** 229 passed.
- **New tests:**
  - Link, PDF, image and audio can each be saved with a note.
  - A blank note becomes no context.
  - Notes over 2000 characters are rejected (link and file).
  - The same video goes to **Python** only when saved with the Python note.
  - A note such as "Ask my doctor…" gives Health.
  - The note is searchable.
  - The note doesn't replace the source title.
  - The AI prompt includes `source`, `context` and the new rule (mocked AI).
  - The page has the single composer and no old drawer.
- **Real browser, throwaway database, offline mode:**
  - Typed the Python note, then **+ Link**, `https://example.com`, Enter. The
    chip showed "LINK https://example.com ×" and the button read "Add link
    with note".
  - **Add** gave "Link saved with your note." The box and chip cleared, and
    the item was filed in **Python**.
  - A PDF with the note "Pay this before the 15th, it's my electricity bill"
    gave "PDF saved with your note." It went to **Money & Admin**, kept the
    file-name title, and got a task from the note.
  - Both cards showed "Your note: …".
  - No console errors.
- **Bug found and fixed during browser testing:** the character counter
  covered the attachment chip's **×** button, so an attachment couldn't be
  removed. The chip now sits below the note box.

## Before pushing

- **Database upgrade needed:** `python -m alembic upgrade head` (adds `0016`).
- The owner's local database was backed up to
  `data/life_inbox.backup-2026-11-02-pre-0016.db` and upgraded.

## Known limits and next steps

- **Offline mode is basic.** It can create an extra task from the source's own
  text (for example "Amount payable 2,340 rupees") and doesn't read dates like
  "before the 15th" as urgent. The AI path handles this better.
- **One attachment per save.**
- **No editing yet.** A note can't be edited after saving; next would be an
  "Edit note" option on source cards.
- **Not yet checked with the live NVIDIA model,** to save credits.
- **Per-source handling** (YouTube metadata, PDF summaries, image description
  plus note, and so on) is planned as separate changes, as agreed.
