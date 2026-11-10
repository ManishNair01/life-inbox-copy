# Life Inbox

This is the local-project version of the Life Inbox Google Colab notebook.
It preserves the features already present in the notebook:

- save a text note or record a voice note directly from the browser;
- capture URLs, PDFs, and images;
- list, edit, and delete saved notes and voice memos;
- organize the entire inbox into buckets, priorities, and ToDos;
- in-app interactive calendar that automatically displays dated items from all capture types;
- Ask My Inbox with citation-grounded answers;
- use the NVIDIA NIM API (or OpenAI-compatible endpoint) when an API key is available;
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

Then visit: <http://127.0.0.1:8000>

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
- **Read-Only API**: Powered by `GET /api/calendar/events?start=YYYY-MM-DD&end=YYYY-MM-DD`, querying existing task and note relations without expensive on-demand AI calls.

## 4. Configure NVIDIA NIM (or Offline Fallback)

Life Inbox works 100% offline out-of-the-box using rule-based deterministic organization and extractive question answering.

To enable live NVIDIA NIM LLM organization, question-answering, and speech transcription, add your key to `.env`:

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

The tests use temporary SQLite databases and do not call OpenAI.

## 6. Optional: add demonstration notes

The original notebook included a utility that adds realistic sample notes.
While the server is stopped, run:

```bash
python -m scripts.seed_demo_notes
```

It uses OpenAI when an API key is available and otherwise uses the notebook's
local fallback list.

## Project layout

```text
life-inbox/
├── app/
│   ├── main.py
│   ├── database.py
│   ├── schemas.py
│   ├── organizer.py
│   ├── templates/index.html
│   └── static/
│       ├── app.js
│       └── styles.css
├── migrations/
│   ├── env.py
│   └── versions/
│       ├── 0001_create_notes_table.py
│       ├── 0002_add_updated_at_to_notes.py
│       ├── 0003_create_inbox_items.py
│       ├── 0004_persist_analysis_results.py
│       ├── 0005_create_tasks.py
│       └── 0006_deduplicate_tasks_by_source.py
├── alembic.ini
├── data/
├── docs/
│   ├── architecture.md
│   ├── manual-testing.md
│   ├── milestone-status.md
│   └── product-roadmap.md
├── scripts/seed_demo_notes.py
├── tests/
│   ├── test_api.py
│   ├── test_calendar.py
│   └── test_migrations.py
├── reference/original_life_inbox_notebook.ipynb
├── .github/workflows/ci.yml
├── AGENTS.md
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

The original notebook remains in `reference/` so you can compare the local
project with the classroom version.
