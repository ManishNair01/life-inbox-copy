# 004: Fix AI creating near-duplicate topics; show subtopics on the dashboard

**Date:** 2026-11-02 · **Status:** Done, not pushed · **Fixes a bug from change 002**

## Problem

After change 002, the **Organized dashboard** showed topics nobody had created:

- `Ideas: Product, business and creative ideas worth keeping.`
- `People: Friends and family: calls, follow-ups, birthdays and favours.`

**Cause:**
- Change 002 sent the user's topics to the AI as text lines like
  `- Ideas: Product, business…` (name, colon, description).
- The real NVIDIA model sometimes copied the **whole line** as the bucket name.
- The app matched names exactly, so "Ideas: Product…" didn't match "Ideas",
  and a new topic was created ("Created from AI organization").
- The tests used a mocked AI that always returned clean names, so they missed it.

**Two related questions from the owner:**
- *Are custom topics private?* Yes: topics are stored per user
  (`topics.owner_user_id`), and the topic list, dashboard, analysis and
  suggestions only use the signed-in user's topics. That wasn't covered by an
  explicit test, though.
- *Why do "Pill Reminder" and "Python" look like extra topics?* The dashboard
  listed every topic flat, so subtopics looked like stray main topics.

## Solution

1. **Unambiguous prompt.** Topics are now sent to the AI as JSON, for example
   `{"name": "Health", "about": "…", "subtopics": [{"name": "Pill reminder", …}]}`.
   The instructions say to copy only the `name`, never the `about` text. The
   same applies to the subtopic-suggestion and delete-reassignment prompts.
2. **Server-side safety net.** Before saving an analysis, every AI bucket name
   is matched to an existing topic:
   - exact match, ignoring case and surrounding quotes, or
   - a known topic name followed by extra text, such as `: …`, ` - …`,
     ` (…)` or ` | …` (the longest topic name wins).

   Buckets that end up with the same topic are merged, so the saved
   "AI-organized inbox" view shows clean names too. A genuinely new name, such
   as "Music practice", still creates a topic as before.
3. **Dashboard nests subtopics.** The *Topics / Spaces* card lists subtopics
   under their parent, and the parent's count includes them.
4. **Privacy test.** A new test proves another user's custom topic is not in
   your topic list, your dashboard, or the topics sent to the AI. It also shows
   that two users can each have a topic with the same name.

## Data repair (owner's local database only)

- The downloaded folder's database was backed up to
  `data/life_inbox.backup-2026-11-02-pre-topic-repair.db`.
- **Topic 31** ("Ideas: Product…", no notes) was removed; its references were
  merged into **Ideas**.
- **Topic 32** ("People: Friends…", 1 note) was removed; the note moved to
  **People**.
- The saved latest analysis now shows **People** instead of the long name.
- No other data was changed.
- **Cooking Ideas, Pill Reminder and Python** were created by the owner and
  were kept.

## Files changed

| File | Change |
|---|---|
| `app/organizer.py` | `_topic_lines()` now outputs JSON (`_topic_entry()`); prompts say to copy only the `name`; suggestion prompt uses JSON |
| `app/database.py` | `_clean_bucket_name()`, `_resolve_existing_topic()`, `_normalize_buckets_to_topics()`; `_topic_id_by_name()` uses them; `complete_analysis_run()` normalizes buckets before saving |
| `app/static/app.js` | `renderDashboardTopics()`: dashboard nests subtopics |
| `app/static/styles.css` | `.dashboard-subtopics` |
| `app/templates/index.html` | Asset version bump |
| `tests/test_topics.py` | Prompt-format test updated; 4 new tests (see below) |
| `decision.md` | Entry for this change |

No database migration is needed.

## How it was tested

- **Full test suite green:** 217 passed.
- **New regression test:** the exact names from the screenshot ("Ideas:
  Product…", "People: Friends…") map to Ideas and People, with no new topics
  and clean saved bucket names.
- Quoted and variant names ("“Recipes”", "recipes (…)") merge into one bucket.
- A genuinely new name still creates a topic.
- A custom topic is invisible to another user in the list, the dashboard and
  the AI input.
- After the repair, the owner's server reloaded and answers normally.

## Not verified

- **Not re-checked against the live NVIDIA model,** because that spends the
  owner's credits. The safety net in step 2 handles the failure even if the
  model repeats it. Running "Analyze Entire Inbox" once with the real key is
  the final check.
