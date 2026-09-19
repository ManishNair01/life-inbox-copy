# Life Inbox

This is the local-project version of the Life Inbox Google Colab notebook.
It preserves the features already present in the notebook:

- save a text note;
- list saved notes;
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

## 3. Optional: configure OpenAI

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

## 4. Start Life Inbox

From the top-level `life-inbox` folder, run:

```bash
python -m uvicorn app.main:app --reload
```

Then open:

<http://127.0.0.1:8000>

Stop the server by pressing `Control+C` in the terminal.

## 5. Run the automated tests

From the top-level `life-inbox` folder, run:

```bash
python -m pytest
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
├── data/
├── scripts/seed_demo_notes.py
├── tests/test_api.py
├── reference/original_life_inbox_notebook.ipynb
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

The original notebook remains in `reference/` so you can compare the local
project with the classroom version.
