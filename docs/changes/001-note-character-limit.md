# 001: Quick Capture stops at 2000 characters

**Date:** 2026-11-02 · **Status:** Done, not pushed

## Problem

Saving a long note (a butter chicken recipe of about 3,800 characters) failed
with the message *"We could not save your note. Your text is still here, please
try again."*

- The server only accepts notes up to **2000 characters** (`raw_text`
  `max_length=2000` in `app/schemas.py`), so it rejected the note with
  `422 Unprocessable Content`.
- The Quick Capture box had no limit, so it let users type or paste far more.
- The page showed the same generic message for every failure, so users had no
  idea the note was too long, and trying again could never work.

## Solution

Keep the 2000-character limit (owner's decision), but enforce it **in the text
box itself** instead of failing after "Add Note".

- The box (`#noteText`) has `maxlength="2000"`: typing stops at the limit, and
  a paste is trimmed to fit.
- A counter sits inside the bottom-right of the box:
  `N / 2000 · max 2000 characters`.
  - It turns amber from 1,800 characters.
  - At 2,000 it turns red, reads `max 2000 characters reached`, and the box
    border turns red.
- If a paste is cut short, a message under the box says only the first part
  was added and suggests saving the rest as another note.
- After a successful save, the counter resets to 0.
- The server limit is unchanged.

## Files changed

| File | Change |
|---|---|
| `app/templates/index.html` | `maxlength="2000"` on `#noteText`; wrapped in `.note-field` with the `#noteCharCount` counter (`aria-live`); asset version bumped |
| `app/static/app.js` | `NOTE_MAX_LENGTH`, `setupNoteLimit()`, `updateNoteCharCount()`, `handleNotePaste()`; `addNote()` guards over-length text and resets the counter |
| `app/static/styles.css` | `.note-field`, `.note-char-count`, `near-limit` / `at-limit` styles |
| `tests/test_api.py` | `test_note_box_is_capped_at_server_limit` |
| `decision.md` | Entry for this change |

## How it was tested

- Full test suite green at the time: 187 passed.
- New test: the page has `maxlength="2000"` and the counter, a 2000-character
  note saves, and a 2001-character note is rejected.
- In a real browser on a throwaway database:
  - Typing from 1,990 characters stopped at exactly 2,000.
  - The counter showed the red "reached" state.
  - The 2000-character note saved.
  - The box and counter reset to 0.

## Notes

- If the server limit ever changes, update `NOTE_MAX_LENGTH` in `app.js` and
  the `maxlength` in `index.html` to match.
