# Life Inbox v2, Phases 4–7: milestone report

**Date:** 2026-11-09 · **Changes:** 016–025 (see `docs/changes/README.md`) ·
**Status:** built and tested in the local work copy; **not pushed**. The
review and the push wait for the owner.

## What was built

| Phase | Change | What you get |
| --- | --- | --- |
| 4 Memory | 016 | "What I learned about you": facts from your choices and your own words, with Confirm / Edit / Delete; health memory off until you allow it; secrets hidden on screen and kept from AI and memory |
| | 017 | Memory hints in filing and "Did a plan move?" questions. **Off** (`LIFE_INBOX_MEMORY_IN_FILING=1` turns it on) until the live replay is OK'd |
| 5 Helpers | 018 | Scout: the day-after question, a weekly catch-up (Sun 19:00), back after a break; Someday; bulk tidy-ups; ✓ in Timeline; "Remind me tomorrow" |
| | 019 | Ask me v2: notes + remembered facts + your tasks for the days asked; every citation checked; "How I answered"; tap-to-run suggestions |
| | 020 | Weekly review (1 call a week): topic proposals ("A new topic?"), facts to confirm; area summaries; Captain's daily AI greeting |
| 6 Sources | 021 | OCR for images (Tesseract), and one vision call for an image with no text and no note |
| | 022 | PDFs keep formula lines; scanned pages read by OCR; a one-time summary for long PDFs |
| | 023 | Edit your note on a saved source; it's filed again |
| 7 Beta | 024 | "Create New Life" setup questions → facts about you |
| | 025 | The AI switch (sign-up box, Settings), Delete my account, privacy and terms for GDPR / DPDP |

**Migrations:** `0027_memory`, `0028_scout`, `0029_weekly_review` and
`0030_source_summary`.

**The owner's database:** upgraded to `0030_source_summary`, each time after
a trial on a copy and a backup:
- `data/life_inbox.backup-2026-11-09-pre-0027.db`
- `data/life_inbox.backup-2026-11-09-pre-0028.db`
- `data/life_inbox.backup-2026-11-09-pre-0029.db`
- `data/life_inbox.backup-2026-11-09-pre-0030.db`

Integrity was OK each time, and the counts were unchanged.

## Quality gate

| Check | Result |
| --- | --- |
| Full pytest suite | **484 passed, 1 failed (the shell test's list of views didn't know the new `welcome` view); after pinning it, `tests/test_shell.py` passes (33), no app code changed in between, so 485 tests pass** |
| Migrations from an empty database | `tests/test_migrations.py` (head `0030_source_summary`) |
| App starts against a temp database | the throwaway server (port 8018) after every change |
| Browser flows | each change's write-up lists its check on the throwaway server |
| Docs | `AGENTS.md`, `docs/architecture.md`, `docs/manual-testing.md`, `docs/deployment.md`, `docs/product-roadmap.md`, `docs/milestone-status.md`, `decision.md`, `docs/changes/016…025` |
| No secrets in the diff | scan for `nvapi-`, `sk-`, AWS, GitHub and Google key shapes: only a made-up test value; `.env`, `data/*.db` and uploads are git-ignored |

## Exact commands

Run these from the project folder (`life-inbox-copy-main`), with the
project's virtual environment.

```bash
python -m pip install -r requirements.txt
```

```bash
set DATABASE_URL=sqlite:///C:/Users/<you>/AppData/Local/Temp/life_inbox_test.db
```

```bash
python -m alembic upgrade head
```

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Tests** (AI keys unset; every AI call is faked):

```bash
python -m pytest -q
```

**Reading text in images** (once, on Windows):

```bash
winget install --id UB-Mannheim.TesseractOCR -e
```

**The weekly review and Scout's push, with the scheduler running:**

```bash
python -m app.notifications.scheduler
```

**The memory replay (017): it spends AI credits, so run it only with the
owner's OK:**

```bash
python -m scripts.memory_replay --live --out docs/changes/017-replay.md
```

## AI calls these changes can make on the owner's account (AI key set)

- **Every day:** 1 greeting.
- **Every week:** 1 weekly review (the first on the next visit).
- **Area summaries:** 1 per area page opened after that area changed.
- **Long PDFs:** 1 summary each, once.
- **Images:** 1 description for an image with no text and no note.
- **Filing and Ask me:** unchanged (1 call; none when nothing matches).
- **Repairs:** at most 1 when a check fails.
- **With the AI switch off:** none at all.

## Waiting for the owner

1. **Review, then the push.** Nothing is pushed or committed. This folder
   isn't a git repository; the earlier changes were never pushed either.
2. **Install Tesseract** (the command above).
3. **The live checks:** 014's NVIDIA check, and 017's memory replay (about 12
   filing calls).
4. **From earlier:**
   - delete the empty topic "Cooking Ideas"?
   - re-file the bird note?
   - drop or re-file the Dhaba task?
5. **Before a public beta:** publish a grievance / privacy contact, and have
   the draft privacy policy and terms reviewed.
