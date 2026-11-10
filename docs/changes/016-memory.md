# 016: Memory, what Life Inbox learns about you (and secrets in notes)

**Date:** 2026-11-09 · **Status:** Done, not pushed · **Part of:** Phase 4
("Now start with Phase 4 to 7 full build").

## What it does

Life Inbox now keeps a short list of facts about you, so it can file your
notes better. Change 017 shows those facts to the filing call; this change
collects them, shows them to you, and lets you change or delete them.

**Where a fact comes from** (and nothing else):

| Source | Example | Starts as |
| --- | --- | --- |
| A note you move to another topic | You filed “College fest stalls” under Work & career. | Confirmed (your choice) |
| A priority you set | You set “Renew the gym membership” to High priority. | Confirmed |
| A date you set | “Team lunch” is on Mon 16 Nov. (kept until a week after) | Confirmed, expires |
| Your answer to Captain's "which area?" | Your topic “Cricket” belongs to Fun & interests. | Confirmed |
| Your own words in a note (filing finds at most 2 per note) | You run your college's events. | **Not confirmed yet**; confirmed when a second note says it again, or when you confirm it |

**Never a source:**
- the text of a link, PDF or image you saved;
- a guess;
- a note that holds a secret.

**Kinds of fact:**
- **long-term:** about you;
- **short-term:** a plan, with an end date;
- **example:** how you file things.

The memory page also shows **Coming up**: your dated open tasks in the next two
weeks. It's read from your tasks, not stored twice.

## Where you see it

- **Area pages:** "What I learned about you" lists that area's facts (5 at a
  time, with "All ›").
- **The new page `#/memory`:** every fact grouped by area (what spans your
  areas comes first), plus Coming up and an explanation. You reach it from:
  - Captain's card ("What I learned ›");
  - the account menu;
  - Settings → Your data.
- **Each fact shows:**
  - where it came from, and "Open the note";
  - **Confirm** (for a suggested fact), **Edit**, and **Delete**. Delete asks
    "Forget it for good?" and erases the words. A deleted fact is never
    suggested again.
- **The export (Markdown)** ends with "What Life Inbox learned about you": each
  fact, its status and the note it came from.

## Health memory: off until you switch it on

- **What it covers:** everything in the Health area (medicines and doctors,
  fitness and food, mind and mood), and any fact with a medical word (doctor,
  pills, thyroid…) whatever area it came from. Those include the medical notes
  you keep about family members.
- **While it's off,** none of it is kept, and you can't edit a fact into one.
- **Switching it off** asks first, then deletes what it held (status
  "deleted", words erased).
- **Where the switch is:** the Health area's memory card and the memory page.

## Secrets in notes (decision J)

These count as secrets:
- passwords and passcodes, PINs and OTPs, CVVs;
- card numbers (Luhn-checked);
- bank account numbers with an IFSC, and Aadhaar and PAN numbers;
- Wi-Fi keys, and API keys and tokens.

The detector is `app/sensitive.py`. It's careful about look-alikes: a postal
"PIN code", a "boarding pass", a "token number" at a clinic and "secret santa"
are not secrets.

**A note that holds one:**
- **Is hidden on screen.** Titles, the note page, the All-notes list, hover
  cards, search results and Ask me citations show `••••` in place of the value.
  The note page has **Show** / **Hide**, and closing the note hides it again.
  Edit still opens the real text (it's yours).
- **Never reaches the AI.** Filing sends it to the offline matcher from a
  masked copy, while the rest of the batch still goes to the AI. It's never a
  "similar note" example. Ask me's evidence, the legacy analyze call and
  re-filing after a topic delete all get masked text, and a voice transcript
  holding one skips the AI tidy-up.
- **Never becomes memory.** A fact that is, or would hold, a secret is
  refused, including on Edit.
- **The one exception,** said on the privacy page: a voice note's audio goes to
  the speech service before Life Inbox can read it.

## API

- **`GET /api/memory?bot=`:**
  - returns `{facts, coming_up, health_memory_consent}`;
  - `bot` is an area key, `captain` (facts across areas) or nothing (all);
  - an unknown area is 422.
- **`PATCH /api/memory/{id}`:** `{text?, status?: "confirmed", core_profile?}`.
  - Editing makes the fact "Added by you".
  - A secret, a duplicate, a health fact without consent, or any other status
    is refused with 422.
- **`DELETE /api/memory/{id}`:** 204. Another user's fact is a 404.
- **`GET/PATCH /api/settings`:**
  - fields: `health_memory_consent`, `ai_processing` (used by 025),
    `catchup_day` and `catchup_time` (018);
  - unknown or read-only fields are 422.
- **Items gain:**
  - `looks_secret`;
  - `secret_masked` (the masked title, text, note and extracted text, or
    null).
- **Insight titles are masked.**

## Database: migration `0027_memory`

- **`memory_facts`:**
  - owner, area (`bot_key`), kind, text;
  - a hash of the normalized text (one row per fact per user, deleted ones
    included, so a deleted fact is never suggested again);
  - source note ids, source kind, status (suggested / confirmed / expired /
    deleted), times seen, valid until, core profile.
- **`user_settings`:** one row per user, made on first use. Health consent is
  off by default and AI processing on.
- **`item_insights.memory_used`:** which facts the filing call was shown (017
  fills it).
- **`plan_updates`:** "Move X from A to B?" questions (017).

**The owner's database:**
- trial on a copy;
- a backup to `data/life_inbox.backup-2026-11-09-pre-0027.db`;
- 0026 → 0027, integrity OK, counts unchanged;
- the server is healthy.

## Tests

- **Full suite:** 419 passed.
- **New: `tests/test_memory.py`** (29 tests):
  - the secret detector, its look-alikes and masking;
  - a secret note hidden and never in a filing, Ask me or search prompt;
  - each source of facts;
  - suggested → confirmed when seen again (and a secret fact from the AI
    dropped);
  - Confirm, Edit and Delete, and deleted facts never coming back;
  - short-term facts expiring;
  - privacy between two users;
  - the health gate, including switching it off;
  - settings checks;
  - memory in the export;
  - secret notes never used as similar-note examples.
- **`tests/test_shell.py`:** the memory view exists; Node tests of
  `memoryGroups`, `memoryStatus` and masked titles and hover text.
- **Updated:**
  - the migration head and columns (`test_migrations.py`);
  - the item shape (`test_api.py`);
  - `test_needs_you.py` no longer looks up example.com in DNS (it failed once
    when the network dropped).
- **Browser check on the throwaway server (port 8018):**
  - the memory page with Edit (focus goes to the box), Delete (focus goes to
    "Keep") and Forget;
  - the health switch on and off (it asks first), and the Health page card;
  - the secret note masked on the note page, in Recent and in All notes;
    Show / Hide; hidden again after closing;
  - no console errors.
