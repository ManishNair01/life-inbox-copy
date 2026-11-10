# 003: Delete user-created topics, and re-home their notes

**Date:** 2026-11-02 · **Status:** Done, not pushed

## Problem

1. **No way to delete a topic.** Users could create topics (change 002) but
   never remove them.
2. **Notes need a new home.** A topic's notes must not be left pointing at a
   topic that no longer exists, and the delete must not cause a crash.
3. **Deleting by accident.** Deleting should ask "Are you sure?" first.
4. **Security gap found while working here.** When setting a note's topic
   manually (`PATCH /api/items/{id}/insight` with `user_topic_id`), the server
   checked the topic existed but **not that it belonged to the user**. A note
   could be pointed at another user's topic.

## Solution

### Who can delete what

- **Topics the user created** (including ones the AI created during
  organizing) show a **Delete** button.
- **The 9 built-in topics** (Work, Health, …) can't be deleted: no button, and
  the API refuses with 400.

### "Are you sure?"

Clicking **Delete** opens a confirmation **inside the topic row**, not a
browser pop-up, saying exactly what will happen:

> Delete "Pill reminder"? Its 1 note will move to Health. This can't be undone.
> **[Yes, delete]  [Cancel]**

The wording depends on the case:
- "…Its N notes will be re-sorted into your other topics."
- "…It has no notes."
- "…Its subtopic 'Desserts' will become a main topic."

**Cancel** closes the box without changing anything.

### Where the notes go

| Deleted topic | Its notes |
|---|---|
| **Subtopic** (Health → Pill reminder) | Move to the **parent** (Health) immediately. If the user had filed a note there by hand, the note goes to the parent and stays marked as the user's choice. |
| **Main topic** (Recipes) | Each note is re-sorted into one of the user's **remaining** topics: by the AI if a key is set, otherwise by the offline keyword matcher. The AI may only choose existing topics, so the deleted topic can't quietly come back. Made-up topic names from the AI are ignored. If nothing fits, the note goes to **Personal / Reference**. |
| **Main topic with subtopics** | Its own notes are re-sorted as above. Its subtopics become main topics and keep their notes. |

### Also handled

- **Saved analysis:** the "AI-organized inbox" panel shows the last saved
  analysis. Its copy is updated so the deleted topic's bucket disappears and
  its notes appear under their new topics.
- **Summary message:** after deleting, a message explains the result, for
  example *"Deleted 'Recipes'. 1 note re-sorted: 1 to Personal / Reference."*
- **One transaction:** the delete runs in a single database transaction, so
  notes are never left half-moved.

## Files changed

| File | Change |
|---|---|
| `app/database.py` | `get_topic_deletion_plan()`, `delete_topic_in_db()`, `_rewrite_latest_analysis_buckets()` and helpers; **security fix**: manual topic override must be the user's own topic |
| `app/organizer.py` | `reassign_notes_to_topics()`: assigns notes only to existing topics (AI, validated, with offline fallback) |
| `app/schemas.py` | `MovedNote`, `TopicDeleteResult` |
| `app/main.py` | **New** `DELETE /api/topics/{topic_id}`: 400 for built-in, 404 for missing or another user's |
| `app/static/app.js` | Delete button on user topics; inline confirmation (`askDeleteTopic`); `deleteTopic()`; summary message; `topicRequest()` helper |
| `app/static/styles.css` | Delete button and confirmation box styles; topic rows laid out side by side |
| `app/templates/index.html` | Asset version bump |
| `tests/test_topics.py` | 10 new tests (see below) |
| `decision.md` | Entry for this change |

No database migration is needed.

## How it was tested

- **Full test suite green:** 213 passed.
- **New tests:**
  - Deleting a subtopic moves its notes, including a hand-filed one, to the
    parent.
  - Deleting a main topic re-sorts its notes into existing topics only.
  - A main topic's subtopics are promoted and keep their notes.
  - The deleted topic disappears from the saved analysis.
  - Deleting an empty topic works.
  - Built-in topics are refused (400).
  - Another user's topic gives 404.
  - **Security:** a note can't be moved to another user's topic (400).
  - AI reassignment ignores made-up topics and unknown notes (mocked AI).
  - Offline reassignment prefers a matching subtopic.
- **Real browser, throwaway database, offline mode:**
  - Only user topics had a Delete button.
  - Delete → **Cancel** kept the topic.
  - Delete "Pill reminder" → **Yes** gave "Deleted 'Pill reminder'. 1 note
    moved to Health."
  - Delete "Recipes" → **Yes** gave "Deleted 'Recipes'. 1 note re-sorted:
    1 to Personal / Reference." The AI-organized inbox panel no longer showed
    Recipes.
  - No console errors.

## Notes

- **Full analysis can still invent topics.** "Analyze Entire Inbox" may still
  invent a new topic when no existing one fits; that's existing behaviour. In
  rare cases it could invent a topic with the same name as one the user
  deleted.
- **Renamed built-in topics.** Built-in topics are recognised by name. A
  built-in topic renamed through the API (not possible from the page today)
  would become deletable.
