# 002: Topics with descriptions and AI-suggested subtopics

**Date:** 2026-11-02 · **Status:** Done, not pushed

## Problem

Adding a topic under **Topics / spaces** saved only its name, and nothing used it.

1. **The AI never saw user topics.** `analyze_inbox` sent the AI only the notes.
   The AI instructions hard-coded the 9 built-in topics (Work, Money & Admin,
   Learning, Shopping & Errands, Health, Travel, Ideas, People,
   Personal / Reference).
2. **Offline mode ignored them too.** `bucket_for_text` used a fixed keyword
   list for the built-in topics only.
3. **A note reached a user topic only by coincidence.** That happened only if
   the AI invented a bucket with exactly the same name, including capital
   letters. Otherwise a duplicate topic was created.
4. **No descriptions, no structure.** There was no way to say what a topic is
   for, and no way to group related topics. For example, "Pill reminder"
   clearly belongs with Health.

## Solution

### Adding a topic is now two steps

1. **Name and description.** The description is required in the form, because
   it's what tells Life Inbox which notes belong in the topic.
2. **Subtopic suggestion.** Life Inbox checks whether the new topic is a
   narrower part of an existing main topic:

   > "Pill reminder" looks like part of Health. Make it a subtopic of Health?
   > *"medicine" is usually a Health topic.*
   > **[Yes, make it a subtopic of Health]  [Keep it as a separate topic]  [Cancel]**

   - **Yes** creates it as **Health → Pill reminder**.
   - **Keep it as a separate topic** creates it as a main topic.
   - If nothing fits, it's created straight away with no question.
   - The suggestion is **advisory only**: nothing is nested unless the user
     agrees.
   - **With an AI key**, the AI makes the suggestion and returns a short reason.
     If it names a topic that doesn't exist, the app ignores it and uses the
     offline matcher.
   - **Without an AI key**, built-in keyword rules (for example "pill" or
     "medicine" → Health) and word overlap with the user's own topics make the
     suggestion.

### Notes are sorted into the user's topics

- The AI now receives the user's full topic list, with descriptions and
  subtopics nested. It is told to use the topic names exactly and to pick the
  **most specific** topic, so a subtopic wins over its parent.
- Offline, notes are matched against the words in the user's own topic names
  and descriptions first, then the built-in rules.
- Bucket names are matched to existing topics **case-insensitively**, so
  "recipes" reuses "Recipes" instead of creating a duplicate.
- After a topic is created, the whole inbox is re-analysed, so existing notes
  that fit move into it.

### Rules

- **One level only:** a subtopic's parent must be a main topic.
- **Personal / Reference** is the catch-all and cannot have subtopics.
- A topic can only be nested under the **same user's** topic.
- The 9 built-in topics remain, and now have descriptions.

### Topic list

- Subtopics appear indented under their parent, labelled "Subtopic of …".
- A parent's count includes its subtopics, for example
  "2 items (1 in subtopics)".

## Files changed

| File | Change |
|---|---|
| `migrations/versions/0015_topic_hierarchy.py` | **New.** Adds `topics.parent_topic_id` (FK to `topics.id`, `ON DELETE SET NULL`) and fills empty descriptions for built-in topics |
| `app/database.py` | `parent_topic_id` on `TopicRecord`; `DEFAULT_TOPIC_DESCRIPTIONS`; `TopicConflictError`; `_validate_parent_topic()`; `topic_name_exists()`; `create_topic_in_db(parent_topic_id=)`; case-insensitive name matching; `total_item_count` roll-up; `is_built_in` |
| `app/organizer.py` | `DEFAULT_TOPIC_RULES` with more Health/Travel/People words; `match_user_topic()`; `suggest_parent_topic()` (AI with offline fallback); `_topic_lines()` for the prompt; `analyze_inbox_with_nvidia(notes, topics=)`; `fallback_analyze(notes, topics)` |
| `app/schemas.py` | `TopicCreate.parent_topic_id`; `TopicParentSuggestionRequest`, `TopicRef`, `TopicParentSuggestion`; `Topic.total_item_count`, `parent_topic_id`, `is_built_in` |
| `app/main.py` | **New** `POST /api/topics/suggest-parent` (saves nothing; 409 if the name exists); `POST /api/topics` accepts `parent_topic_id` (400 on rule breaks); `/api/analyze` passes the user's topics |
| `app/templates/index.html` | Two-step topic form (name, description, Next) and the suggestion box |
| `app/static/app.js` | `createTopic()`, `confirmTopic()`, `cancelTopicSuggestion()`; nested topic list; re-sort after creation |
| `app/static/styles.css` | Styles for the form, suggestion box and indented subtopics |
| `tests/test_topics.py` | **New.** 16 tests (see below) |
| `tests/test_api.py` | Analyzer test stubs accept the new `topics` argument |
| `tests/test_migrations.py` | Expect head `0015_topic_hierarchy` and the new column |
| `decision.md` | Entry for this change |

## How it was tested

- **Full test suite green:** 203 passed.
- **New tests in `tests/test_topics.py`:**
  - Built-in topics have descriptions.
  - Offline suggestion: "Pill reminder" → Health; "Recipes" → none.
  - Suggesting never saves anything.
  - A duplicate name gives 409.
  - Subtopics and the catch-all are never suggested as parents.
  - Creating as a subtopic, and as a separate topic.
  - Nesting is limited to one level.
  - The catch-all cannot have subtopics.
  - Nothing can be nested under another user's topic.
  - Offline analysis files notes into the most specific topic, with parent
    totals rolled up.
  - The analyzer receives the user's topics, and AI bucket names match topics
    case-insensitively.
  - AI suggestion (mocked; no live API calls):
    - Only main topics are offered.
    - A made-up topic name falls back to offline.
    - A null answer means no suggestion.
  - The analysis prompt lists topics with nested subtopics and the
    "most specific" rule.
- **Real browser, throwaway database, offline mode:**
  - "Pill reminder" with a medicines description → Health suggested →
    **Yes** → created under Health. The medicines note moved in, and Health
    showed "2 items (1 in subtopics)".
  - "Recipes" → no suggestion → created straight away; the butter chicken
    note moved in.
  - "Vitamins" → Health suggested → **Keep it as a separate topic** → created
    as a main topic.
  - No console errors.

## Before pushing

- **Database upgrade needed:** run `python -m alembic upgrade head` (adds
  `0015_topic_hierarchy`). The app refuses to start until this is done, and
  tells you what to run.
- The downloaded folder's own database was backed up to
  `data/life_inbox.backup-2026-11-02-pre-0015.db` and upgraded.

## Not included (possible next changes)

- A **"Move to topic"** option on each note. The server already supports it
  (`PATCH /api/items/{id}/insight` with `user_topic_id`), but there is no
  button on the page.
- Editing an existing topic's description, or moving it under or out of a
  parent.
- The AI suggestion was tested with a mocked AI, not the live NVIDIA model,
  to avoid spending credits. Try it once with your key and check the
  suggestions make sense.
