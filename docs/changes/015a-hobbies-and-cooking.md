# 015a: Hobbies, with Cooking inside it

**Date:** 2026-11-08 · **Status:** Done, not pushed · **Asked for by:** the owner,
"Cooking and Hobbies should not be together. Inside Hobbies - Cooking is okay".

## What changed

- **Fun & interests now has:**
  - Watch, read & listen;
  - **Hobbies** (games, crafts, music you play, sport, collecting, creative
    pursuits);
  - **Hobbies › Cooking**, a built-in subtopic (recipes, dishes to cook,
    cooking ideas);
  - Trips & places.
- **Migration `0026_hobbies_and_cooking`, for every account:**
  - "Cooking & hobbies" is renamed Hobbies, and Cooking is added under it.
  - Notes the AI filed there that are about food move into Cooking; others
    stay in Hobbies. Notes you placed yourself stay where you put them.
  - A top-level topic of yours called "Cooking" would become the subtopic,
    instead of a second one being made.
  - The saved analysis view is renamed.
- **New accounts** get the same structure: 15 main topics, plus Hobbies ›
  Cooking.
- **Filing's offline rules** know the two apart (recipe, cook, paneer → Cooking;
  guitar, chess, painting → Hobbies).
- **A new topic's parent suggestion:** "Recipes" suggests Hobbies, because its
  words go with Cooking, which sits under Hobbies.

## The owner's database

- **Trial on a copy,** then a backup to
  `data/life_inbox.backup-2026-11-08-pre-0026.db`, then 0025 → 0026. Integrity
  OK.
- **The two butter chicken notes moved into Cooking.** The bird note stays in
  Hobbies, still waiting for the owner's say on re-filing it.
- **The owner's old, empty "Cooking Ideas" topic is untouched,** waiting for
  their OK to delete it.

## Tests

- **Full suite:** 389 passed.
- **New:** `tests/test_hobbies_migration.py`. Food notes move to Cooking, others
  stay, your own pick is kept, and the saved view is renamed.
- **Updated:** the defaults (16 topics, Fun & interests 4); "Chess openings" is
  now a hobby; the replay table's recipe note expects Cooking.
