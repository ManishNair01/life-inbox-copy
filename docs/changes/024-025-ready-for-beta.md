# 024–025: Ready for beta (Phase 7)

**Date:** 2026-11-09 · **Status:** Done, not pushed: the push waits for the
owner's OK. **Decision Q:** AI stays on for existing accounts, is asked at
sign-up (unticked means off), and has a switch in Settings for everyone.

## 024: "Create New Life" onboarding

**When it shows:** right after sign-up, the app opens **Create New Life**
(`#/welcome`). It only appears for a new account with no notes that hasn't
answered or skipped. Anyone can open it later from Settings ("Tell Life Inbox
about you").

**The questions** (all optional):
- what you do (I study / I work / Both / I run a home / something else);
- where you're based;
- what fills your days (any of 9 areas);
- anyone you look after;
- **Remember health facts**, with the family-members wording: "About you and
  the people you care for, such as family members: medicines, doctors,
  appointments. Off unless you switch it on."

**The answers:**
- **Saved as confirmed core-profile facts** (016), marked "About you" on the
  memory page, where they can be edited or deleted. The weekly review and
  017's filing hints use them.
- **Health consent is set first,** so "my parents' medicines" is kept only
  with it.
- **Skip for now** works, and filing works with no memory at all.

**A bug this caught:** the health gate's word list matched "medicine" but not
"medicines" (nor "doctors" or "hospitals"). So a plural medical fact could
have been kept without consent. Plurals now count; there's a regression test.

## 025: Privacy and compliance, the AI switch, deleting your account

**The AI switch (decision Q):**
- **One gate in `app/llm.py`.**
  - `llm.allowed()` reads the signed-in user's `user_settings.ai_processing`
    through a check that `app/database.py` registers. `is_configured()` is
    false when it's off, and `complete_text` itself refuses
    (`AiSwitchedOff`). So every feature falls back to its no-AI path, and
    nothing is sent.
  - **It fails closed:** if the switch can't be read, AI is treated as off.
  - **Scripts with no signed-in user** are allowed, as before.
- **Sign-up:** the box "Let Life Inbox use AI (NVIDIA) to file and summarise
  my notes…" starts **unticked**. API clients that leave the field out keep
  AI on, as existing accounts do.
- **Settings → AI processing:** the switch, what's sent with it on, and what
  you get with it off (rule-based filing, quoted answers, no greeting,
  summaries, weekly review, image description or voice transcription).

**Delete my account** (the right to erasure):
- **Where:** Settings has a danger card that offers the export first.
- **The checks:** your password and typing DELETE
  (`POST /api/auth/account/delete`). A wrong password changes nothing (403).
- **What goes:**
  - every row of yours in every table, children first, by the tables'
    dependency order (foreign keys are enforced);
  - your uploaded files;
  - your sign-ins;
  - then the account itself.
- **Afterwards,** the sign-in page says "Your account and everything in it
  were deleted."

**The privacy policy** (draft 2026-11-09) adds:
- the AI switch;
- every newer feature that sends data (greeting, area summaries, weekly
  review, Ask me, long-PDF summaries, image descriptions);
- how long data is kept, and deletion (including that the operator's backups
  may hold it until replaced);
- rights under the GDPR and India's DPDP Act 2023: access and portability
  (export), correction, erasure, withdrawing consent (the AI and health
  switches), and complaints (the Data Protection Board of India, or a
  nominee).

The grievance contact is still to be published by the operator: it can't be
invented here.

**The terms** add in-app deletion and an "AI features" section (AI output can
be wrong; it's marked, kept apart, and never acted on without you).

## Tests

- **Full suite:** 484 passed, 1 failed (the shell test's list of views didn't know the new `welcome` view); after pinning it, `tests/test_shell.py` passes (33), no app code changed in between, so 485 tests pass.
- **New: `tests/test_beta.py`** (11 tests):
  - a new account is asked, and the answers become core facts (with health
    consent);
  - a medical answer without consent isn't kept;
  - skipping works, and filing works with no memory;
  - an existing account isn't asked;
  - sign-up unticked means AI off and **no AI call at all** (filing and Ask
    me);
  - the Settings switch on and off;
  - older clients keep AI on;
  - the gateway itself refuses when it's off;
  - the sign-up box starts unticked;
  - deleting erases only your data (a wrong password or word deletes
    nothing; the files go; the other user's notes stay);
  - the policy pages cover the beta.
- **Plus** a regression test for plural medical words in
  `tests/test_memory.py`.
- **Browser check (throwaway server, port 8018):**
  - sign-up through the real form, with the AI box unticked: AI off, and
    straight to Create New Life;
  - the answers saved 4 "About you" facts;
  - the Settings switch on and off, with its messages;
  - deletion refused the wrong word, then deleted the account and showed the
    message;
  - every request in the flow succeeded (the final 401 was my own check that
    the account was gone).
