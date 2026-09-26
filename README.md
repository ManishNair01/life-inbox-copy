# Life Inbox

This is the local-project version of the Life Inbox Google Colab notebook.
It preserves the features already present in the notebook:

- save a text note;
- list, edit, and delete saved notes;
- organize the entire inbox into buckets, priorities, and ToDos;
- use the OpenAI API when an API key is available;
- use the notebook's deterministic fallback organizer otherwise.

## 1. Requirements

- Python 3.10 or newer
- A terminal
- An OpenAI API key is optional. The fallback organizer works without one.

## 2. Set up the project

Open a terminal, enter this folder, and create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows, activate it with:

```powershell
.venv\Scripts\activate
```

Install the dependencies:

```bash
python -m pip install -r requirements.txt
```

## 3. Configure and migrate the database

Life Inbox uses SQLite by default at `data/life_inbox.db`. To use another
database location, set `DATABASE_URL` before running Alembic or the app:

```bash
export DATABASE_URL="sqlite:////absolute/path/to/life_inbox.db"
```

For a new or empty local database, apply all migrations with:

```bash
python -m alembic upgrade head
```

For an existing `data/life_inbox.db`, make a backup and then run the same
upgrade:

```bash
cp data/life_inbox.db data/life_inbox.db.backup
python -m alembic upgrade head
```

The initial migration detects the existing `notes` table, validates its
required columns, and adopts it without deleting or copying any notes. Check
the applied revision with:

```bash
python -m alembic current
```

The application does not run Alembic migrations automatically at startup.

### Canonical inbox-item model

The canonical API is `/api/items`. The browser uses this API for text-item
creation, listing, editing, and deletion. Items include:

- `id`, `item_type`, and `processing_status`;
- optional `title`, `source_url`, `original_filename`, and `mime_type`;
- `raw_text`, `created_at`, and optional `updated_at`.

Only `item_type="text"` is created or displayed in this version. File uploads,
URLs, voice, and image inputs are not implemented.

The `/api/notes` routes remain temporarily available as deprecated
compatibility adapters. They read and write the same `inbox_items` records
while preserving the former note response shape. Migration `0003` copies
legacy notes into `inbox_items` with the same IDs and timestamps. The legacy
`notes` table is retained unchanged as a migration safety copy and is no
longer authoritative.

## 4. Optional: configure OpenAI

If you want AI analysis instead of the local fallback, set your API key in the
terminal before starting the application:

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_MODEL="gpt-5-mini"
```

On Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your-api-key"
$env:OPENAI_MODEL="gpt-5-mini"
```

Do not put the real key in source code or commit it to Git.

## 5. Start Life Inbox

From the top-level `life-inbox` folder, run:

```bash
python -m uvicorn app.main:app --reload
```

Then open:

<http://127.0.0.1:8000>

Stop the server by pressing `Control+C` in the terminal.

## 6. Run the automated tests

From the top-level `life-inbox` folder, run:

```bash
python -m pytest
```

The tests use temporary SQLite databases and do not call OpenAI.

## 7. Optional: add demonstration notes

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
│       └── 0003_create_inbox_items.py
├── alembic.ini
├── data/
├── scripts/seed_demo_notes.py
├── tests/
│   ├── test_api.py
│   └── test_migrations.py
├── reference/original_life_inbox_notebook.ipynb
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

The original notebook remains in `reference/` so you can compare the local
project with the classroom version.
