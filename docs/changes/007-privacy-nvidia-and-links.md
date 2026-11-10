# 007: Privacy policy names NVIDIA and explains link fetching

**Date:** 2026-11-02 · **Status:** Done, not pushed · **Build plan:** phase 1

## Problem

The draft privacy page (`/privacy`) no longer matched what the app does:

- **It named the wrong AI company.** It said content "may be sent to OpenAI",
  but Life Inbox now sends notes, link text and voice audio to **NVIDIA**.
- **It didn't mention link fetching.** Saving a link makes the server fetch
  that page, so the website (YouTube for YouTube links) receives the link and
  the server's address.
- **It didn't cover the new AI call log** from change 006.

Both GDPR and India's DPDP Act require users to be told who receives their
data. The design doc marked this as **must be done before beta**.

## Solution

The privacy page (still marked "Draft for private beta") now says:

- **What we collect:** "Your content" includes the note you write about a saved
  source (change 005). A new **"AI usage records"** item covers the call log:
  which feature, the model, whether it worked, its size and duration, and never
  the text.
- **AI processing:** NVIDIA (NVIDIA NIM) runs the AI model. For each feature,
  it says what is sent:
  - **Organizing a note:** the note, your note about a source, and the source's
    text.
  - **Voice memos:** the audio for transcription, then the transcript, to tidy
    it.
  - **Ask My Inbox:** the question and the few matching passages.
  - **Creating a topic:** its name and description, and your topic names.

  It also says that email, name and password are never sent; that if an
  operator uses OpenAI instead, the same content goes to OpenAI; and that a
  per-user AI switch is planned.
- **Links you save (new section):** the server fetches the page, so the site
  receives the link and the server's address (YouTube/Google for YouTube
  links). Your browser doesn't contact the site, and none of your accounts or
  cookies are used. This was checked in the code: links are fetched on the
  server, and the page shows no images from other sites.
- **Who can see your content:** the AI provider receives only what's described
  under AI processing.
- **Version** updated to draft 2026-11-02.

## Files changed

| File | Change |
|---|---|
| `app/templates/privacy.html` | NVIDIA, what each feature sends, link fetching, AI usage records |
| `tests/test_privacy_page.py` | **New.** 3 tests |

## How it was tested

- **Full test suite:** 251 passed (3 new).
- **New tests:**
  - the page names NVIDIA, lists all four uses, says passwords are never sent,
    and no longer says content "may be sent to OpenAI";
  - it explains link fetching, including YouTube;
  - it discloses the AI usage records and says they never hold text.
- **In the browser:** `/privacy` shows the new sections, with no console
  errors.

## Before pushing

- No database change.

## Known limits and next steps

- **Still a draft, not reviewed by a lawyer.** Before public launch it must
  also say where NVIDIA processes data and how long it keeps it. The page says
  so itself.
- **Later changes add their own sections:** smart link capture (015, oEmbed and
  page data), memory (016) and health consent (016, 024). Change 025 is the
  full pre-beta review.
- The per-user AI switch is decision Q in the build plan.
