# 006: One path for every AI call, and Ask's NVIDIA 404

**Date:** 2026-11-02 · **Status:** Done, not pushed · **Build plan:** phase 1

## Problem

- **AI clients were created in four separate places:** inbox analysis and the
  topic helpers in `app/organizer.py`, Ask in `app/retrieval/ask.py`, and
  speech-to-text plus transcript clean-up in `app/capture/voice_extract.py`.
  Each chose its own key, model and settings.
- **No call was counted, timed or size-checked,** so the build plan's limits
  (at most 1.2 calls per added note, prompt-size caps) could be neither
  enforced nor measured.
- **There was no timeout,** so a stuck request could hang for the AI library's
  default of 10 minutes.
- **Ask My Inbox failed once in your log** with NVIDIA `404 Not Found`, and
  fell back to its basic answer.
- **Found along the way:** voice transcription added "nvapi-" to any key,
  which would break an OpenAI key.

## What we found about the 404

- The server log showed `openai.NotFoundError: Error code: 404` from Ask's
  request. Inbox analysis, with the same key, model and address, worked
  minutes before.
- Listing the models the account can use (a free request) showed the
  configured model, `nvidia/nemotron-3.5-bolt-e4b`, is available.
- A 5-token test reply, and three replays of Ask's exact request with made-up
  evidence, all succeeded in 1.0–1.6 seconds.
- **So nothing in our code or settings was wrong.** Most likely NVIDIA briefly
  reported the model as unavailable. That can't be proven after the fact, so
  the fix is defensive (below).

## Solution

### One path: `app/llm.py`

Every AI call now goes through one module:

- **Settings in one place:** the key (NVIDIA first, otherwise OpenAI), the
  model and the address.
- **Timeouts:** 60 seconds for text (set with
  `LIFE_INBOX_AI_TIMEOUT_SECONDS`) and 180 seconds for speech-to-text.
- **A size limit:** a caller can set a maximum prompt size, and a prompt over
  it is refused without being sent. Today's features set no limit yet, so they
  behave exactly as before. The new filing call (014) and memory (017) will use
  it.
- **One quick retry when the provider says "not found"** on a text request.
  The AI library already retries rate limits, timeouts and server errors, but
  not 404. A genuinely wrong model name fails again and falls back as before.
- **An optional repair request for JSON answers:** if an answer can't be used,
  one more request names the problem. It's off for today's features, so their
  behaviour is unchanged. The filing engine (014) and Ask v2 (019) will turn it
  on.
- **The call log** (`ai_calls`): one row per request, with the user, action,
  model, outcome (`ok`, `invalid`, `error` or `too_large`), attempt, the
  provider's status code, sizes and duration. **Never the prompt or the
  answer.** Calls made outside a signed-in request (scripts, unit tests) aren't
  logged.

### Used everywhere

| Feature | Action name in the log |
|---|---|
| Inbox analysis (one note or the whole inbox) | `analyze` |
| Subtopic suggestion when creating a topic | `suggest_parent` |
| Re-homing notes from a deleted topic | `reassign_topics` |
| Ask My Inbox | `ask` |
| Voice: speech-to-text | `voice_transcribe` |
| Voice: transcript clean-up | `voice_cleanup` |

Each feature keeps its own fallback. When a call fails, it uses the offline
path exactly as before.

### Small fixes along the way

- **The key prefix:** "nvapi-" is now added only to NVIDIA keys. An OpenAI key
  is used as given; voice transcription used to turn `sk-…` into
  `nvapi-sk-…`.
- **The transcript clean-up model:** clean-up now uses the same text model as
  everything else (`NVIDIA_LLM_MODEL`, otherwise `OPENAI_MODEL`). With NVIDIA
  set up, that's the same model as before.

## Files changed

| File | Change |
|---|---|
| `app/llm.py` | **New.** The one path: settings, client, timeouts, size limit, retry, repair request, call log |
| `migrations/versions/0017_ai_call_log.py` | **New.** The `ai_calls` table |
| `app/database.py` | `AiCallRecord`, `record_ai_call()`, `list_ai_calls()` |
| `app/organizer.py` | Analysis, subtopic suggestion and re-homing go through `app/llm.py`; its own client code is removed. `extract_json_object` now lives in `app/llm.py` and is still importable from here. |
| `app/retrieval/ask.py` | Ask goes through `app/llm.py`; an unusable answer is logged as `invalid` |
| `app/capture/voice_extract.py` | Speech-to-text and clean-up go through `app/llm.py`; the key-prefix fix |
| `tests/test_llm.py` | **New.** 19 tests |
| `tests/test_migrations.py` | The newest migration is now `0017`; the `ai_calls` columns are checked, and none holds text |
| `AGENTS.md`, `docs/architecture.md`, `docs/deployment.md` | The new rule (all AI calls through `app/llm.py`), the NVIDIA settings, the timeout setting and the call log |

## How it was tested

- **Full test suite:** 248 passed (229 before, plus 19 new).
- **New tests**, all with the AI faked:
  - No file in `app/` creates an AI client except `app/llm.py`.
  - Calls are logged per user, with sizes only. A unique topic name sent to the
    AI appears nowhere in the database afterwards.
  - Each user sees only their own log, and calls outside a signed-in request
    aren't logged.
  - A provider 404 gets exactly one retry; two 404s give up; other errors
    aren't retried.
  - An unusable JSON answer is logged as `invalid`. A repair request names the
    problem and happens at most once.
  - A prompt over the limit is never sent.
  - Every request has a timeout: 60 seconds by default, adjustable, and 180 for
    audio.
  - The key-prefix rule.
  - **Ask:**
    - a real answer through the new path;
    - recovery from one 404;
    - falling back after two 404s;
    - an answer citing a made-up note is rejected.
  - A voice note logs both speech-to-text and the clean-up.
- **The tests really check the retry:** with the 404 retry deliberately
  broken, the three retry tests failed. The code was then restored.
- **Live check with NVIDIA** (a throwaway database, made-up notes, a few
  credits):
  - two notes were filed (about 4.2 seconds each);
  - the subtopic suggestion put "Pill reminder" under Health;
  - Ask returned a real model answer, with high confidence and a citation;
  - all four calls were logged with sizes and timings, and no text.

## Before pushing

- **A database upgrade is needed:** `python -m alembic upgrade head` (adds
  `0017_ai_call_log`).
- Your database was backed up to
  `data/life_inbox.backup-2026-11-02-pre-0017.db` and upgraded, and the server
  was restarted.
- When account deletion is built (auth plan), it must delete the user's
  `ai_calls` rows too, and account export should include them.

## Known limits and next steps

- **The size limit isn't applied to today's features yet.** "Analyze Entire
  Inbox" still sends every note; change 014 fixes that.
- **The repair request is off for today's features;** 014 and 019 turn it on.
- **Nothing in the app shows the call log yet.** It's there to measure the
  build plan's limits (plan §6 and §8).
- **If NVIDIA's 404 comes back,** the log will show it (status code 404) and
  how often the retry saved the answer.
