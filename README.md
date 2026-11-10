# Life Inbox

This is the local-project version of the Life Inbox Google Colab notebook.
It preserves the features already present in the notebook:

- save a text note or record a voice note directly from the browser;
- capture URLs, PDFs, and images;
- list, edit, and delete saved notes and voice memos;
- organize the entire inbox into buckets, priorities, and ToDos;
- add and edit your own tasks (text, priority, due date) alongside the AI-generated ones;
- in-app interactive calendar that automatically displays dated items from all capture types;
- Ask My Inbox with citation-grounded answers;
- email + password accounts (with strict password rules) or Sign in with Google; every user only sees their own data;
- optional browser notifications (daily digest and one-hour alerts for timed High-priority tasks);
- use the NVIDIA NIM API when `NVIDIA_API_KEY` is set;
- use the deterministic fallback organizer and extractive QA otherwise.

## 1. Quick Start (One Command)

If you just cloned or pulled this repository, run the setup script to create `.venv`, install dependencies, set up `.env`, and apply database migrations automatically:

On **Linux / macOS**:
```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

On **Windows (PowerShell)**:
```powershell
.\scripts\setup.ps1
```

Once complete, start the application:
```bash
# Linux / macOS:
./.venv/bin/python -m uvicorn app.main:app --reload

# Windows:
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Then visit: <http://127.0.0.1:8000>. You are sent to the sign-in page the first
time: choose **Create account** (email + password, 10+ characters, 18+ and Terms
confirmation) and you land in your own inbox.

### Accounts and sign-in

- **Password rules** (checked live on the form and again on the server, for sign-up, reset and change):
  10-128 characters with an upper-case letter, a lower-case letter, a number and a symbol; not a common
  password; no run of 4+ identical characters or easy sequences like `1234`/`abcd`; must not contain your
  email name, your name or the app name. Existing passwords keep working.
- **Sign in with Google** is optional and appears only when `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`
  are set in `.env`. To set it up: in the [Google Cloud Console](https://console.cloud.google.com/) create a
  project, configure the OAuth consent screen (External, Testing, add yourself as a test user), create an
  OAuth client of type *Web application* with the authorized redirect URI
  `http://127.0.0.1:8000/auth/google/callback` (must match `GOOGLE_REDIRECT_URI` exactly), then copy the ID and
  secret into `.env`. New accounts via Google must tick the 18+ and Terms boxes first. If the Google email
  already has a password account, the two are linked, the old password is removed and other sessions are
  signed out (use *Forgot password* to set a new one).
- **Password-reset email**: by default codes are printed in the server terminal. To send real email set
  `LIFE_INBOX_EMAIL_PROVIDER=smtp` plus `LIFE_INBOX_SMTP_HOST`, `LIFE_INBOX_SMTP_PORT` (587 default; 465 uses
  SSL), `LIFE_INBOX_SMTP_USER`, `LIFE_INBOX_SMTP_PASSWORD` and optionally `LIFE_INBOX_SMTP_FROM` (for Gmail use
  `smtp.gmail.com` and an [app password](https://support.google.com/accounts/answer/185833)).

- Every page and API route except sign-in, Privacy, Terms and `/api/health`
  needs a session; there is no anonymous mode.
- **Forgot password** sends a 6-digit code. In local development the "email" is
  printed in the terminal running the server (`LIFE_INBOX_EMAIL_PROVIDER=console`).
  Operator fallback: `python -m scripts.reset_password --email you@example.com`.
- After pulling changes that add migrations, run `python -m alembic upgrade head` (back up `data/life_inbox.db` first); the app refuses to start on an out-of-date database.
- Data created before accounts existed belongs to a built-in `local@life-inbox.local`
  user. Register first, then move it into your account with
  `python -m scripts.claim_local_owner --to-email you@example.com --dry-run`
  (drop `--dry-run` to apply).

## 2. Voice Input Note Taking

Life Inbox includes built-in voice note capture:
- **Microphone Button**: Located right next to the note input area. Click to record, click again to stop.
- **4 Visual States**:
  1. *Idle*: Ready to record (`🎙️ Record note`).
  2. *Recording*: Live pulsing red indicator + dynamic elapsed timer (`00:05`).
  3. *Processing*: Animated spinner (`Transcribing…`) while NVIDIA NIM transcribes and cleans the note.
  4. *Error*: Helpful feedback if microphone permission is denied or unsupported.
- **AI Speech Pipeline**:
  1. Audio is captured via browser `MediaRecorder` (`audio/webm` / `audio/wav`).
  2. ASR Transcription via NVIDIA NIM using `NVIDIA_ASR_MODEL` (default: `openai/whisper-large-v3`).
  3. Intelligent LLM Cleanup via NVIDIA NIM LLM (`meta/llama-3.1-70b-instruct`) removes stutters, filler words ("um/uh/like"), and repetitions while strictly preserving every fact, date, number, and name.
  4. Cleaned text is stored in `raw_text` for notes, search, tasks, and analysis; the original verbatim transcript is preserved in `extracted_text`.
- Voice notes can be played back, edited, and deleted just like any text note.

## 3. In-App Calendar for Dated Items

Life Inbox includes an integrated, responsive in-app calendar embedded directly in the workspace:
- **Zero Manual Step**: Notes captured via text, voice recordings, URLs, PDFs, or images that name a date or time (e.g. "dentist on 3 Nov", "call mom tomorrow") appear automatically on the calendar upon ingestion. Items without dates are excluded.
- **Month View with Event Indicators**: Days with events show visual event dots and counts. Controls allow switching between previous/next months and returning to "Today".
- **Day Inspector & Note Linking**: Clicking any day displays scheduled items with their title, source type badge (`text`, `voice`, `url`, `pdf`, `image`), and priority. Clicking "View source note" smoothly scrolls to and highlights the original note in the inbox.
- **Guessed dates wait for your OK**: A guess such as "renew insurance by next Friday" or "call mom this weekend" is only a suggestion (a dashed chip, "Fri 20 Nov? · confirm"). It joins the calendar once you confirm it or pick another day in the small calendar. The app asks right after you save the note.
- **Lifecycle Handling**: Completed tasks are shown struck through; dismissed tasks are hidden. Deleting or editing a note immediately updates the calendar.
- **Manual tasks**: A task added from the Tasks form with a due date appears on the calendar immediately, and the calendar jumps to that month. Use **Edit** on any open task to change its text, priority or due date (clearing the date removes it from the calendar). Edited text and priority are kept when notes are re-analyzed.
- **Natural timing**: Phrases such as `today`, `tonight`, `this evening`, `tomorrow`, `next Friday`, `3 Nov` and `in 3 days` are understood; "Preview calendar" on a task shows a preview (and an explicit confirm step) but never writes to a real Google Calendar.
- **Read-Only API**: Powered by `GET /api/calendar/events?start=YYYY-MM-DD&end=YYYY-MM-DD`, querying existing task and note relations without expensive on-demand AI calls.

### Completing and deleting notes

Completing a note hides it, and its AI analysis, from the active views (AI-organized inbox, dashboard, topic counts); reopening its task brings it back. Deleting a note removes it, its analysis, and any task that came only from that note.

## 3b. Browser Notifications (optional)

Opt in from **Task notifications** in the app. A daily digest lists tasks due today, and High-priority AI tasks with an explicit time also get an alert one hour before. This needs HTTPS (localhost is fine), browser permission and VAPID keys in `.env`; a worker must run once a minute (`python -m app.notifications.scheduler`, or the `notifications` service in `docker-compose.yml`). Key generation and deployment details are in `docs/deployment.md`.

## 4. Configure NVIDIA NIM (or Offline Fallback)

Life Inbox works 100% offline out-of-the-box using rule-based deterministic organization and extractive question answering.

To enable live NVIDIA NIM LLM organization, question-answering, and speech transcription, add your NVIDIA key to `.env` (only an NVIDIA key is needed; a bare key is automatically given the `nvapi-` prefix):

```bash
NVIDIA_API_KEY=nvapi-your-key-here
NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1
NVIDIA_LLM_MODEL=nvidia/nemotron-3.5-bolt-e4b
NVIDIA_ASR_MODEL=openai/whisper-large-v3
DATABASE_URL=sqlite:///data/life_inbox.db
```

Never commit `.env` to Git. `.env` is loaded automatically on startup via `python-dotenv`.

## 5. Run the Automated Tests

Run the test suite with pytest (all tests mock external AI calls with 0 paid/network requests):

```bash
# Linux / macOS:
./.venv/bin/python -m pytest -v --tb=short

# Windows:
.\.venv\Scripts\python.exe -m pytest -v --tb=short
```

The tests use temporary SQLite databases and never call live AI services.

## 6. Optional: add demonstration notes

The original notebook included a utility that adds realistic sample notes
(`python -m scripts.seed_demo_notes`). **It currently does not work**: it was
written before accounts existed and fails with "Authentication required" because
it does not sign in as a user. Until it is updated, add sample notes through the
app or the `/api/items` endpoint.

## Project layout

```text
life-inbox/
├── app/
│   ├── main.py              # routes, auth gate, security headers
│   ├── database.py          # models and persistence
│   ├── schemas.py           # request/response contracts
│   ├── organizer.py         # NVIDIA NIM + deterministic fallback organizer
│   ├── auth.py, config.py   # accounts/sessions, password rules, startup config
│   ├── google_auth.py       # Sign in with Google (OAuth + PKCE)
│   ├── email_sender.py, storage_backend.py, similarity.py
│   ├── capture/             # URL, PDF, image, voice processing
│   ├── retrieval/           # search and Ask My Inbox
│   ├── attention/           # date/timing parsing, attention board
│   ├── integrations/        # calendar adapter (mock / preview-only)
│   ├── notifications/       # Web Push service, dispatcher, scheduler
│   ├── templates/           # index, login, privacy, terms
│   └── static/              # app.js, auth.js, styles, service worker
├── migrations/versions/     # Alembic revisions 0001 to 0016
├── alembic.ini
├── data/                    # local SQLite DB and uploads (git-ignored)
├── docs/                    # architecture, deployment, manual testing, roadmap
├── scripts/                 # setup, reset_password, claim_local_owner, seed_demo_notes
├── tests/                   # pytest suite
├── reference/original_life_inbox_notebook.ipynb
├── .github/workflows/ci.yml
├── AGENTS.md                # guidance for contributors and coding agents
├── decision.md              # running log of changes and decisions
├── docker-compose.yml, Dockerfile
├── .env.example
├── requirements.txt
└── README.md
```

The original notebook remains in `reference/` so you can compare the local
project with the classroom version.
