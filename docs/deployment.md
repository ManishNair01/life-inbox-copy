# Deployment guide (private beta foundation)

This milestone adds a **minimum responsible** multi-user beta foundation.
It intentionally stops before paid infra, real Google OAuth consent, or
public production deploy unless an owner explicitly authorizes those steps.

## Environments

| Env | DB | Auth | Notes |
| --- | --- | --- | --- |
| `local` (default) | SQLite | Dev login allowed; anonymous maps to local owner | Temp DBs for agents/tests |
| `beta` | PostgreSQL required | Dev login must be off | Signed session cookies |
| `production` | PostgreSQL required | Same as beta | Not enabled in this teaching build |

## Required environment variables

```bash
LIFE_INBOX_ENV=local|beta|production
DATABASE_URL=sqlite:////tmp/life_inbox.db   # or postgresql+psycopg://...
LIFE_INBOX_UPLOAD_DIR=/data/uploads
LIFE_INBOX_SESSION_SECRET=<32+ random chars>   # required in beta/production
LIFE_INBOX_AUTH_MODE=dev|google_stub
LIFE_INBOX_ALLOW_DEV_LOGIN=1|0
LIFE_INBOX_TIMEZONE=UTC
LIFE_INBOX_MAX_UPLOAD_MB=5
LIFE_INBOX_CALENDAR_PROVIDER=mock|google
```

Optional: `GEMINI_API_KEY` for live organization only (never in automated tests).

## Local run

```bash
export DATABASE_URL="sqlite:////tmp/life_inbox_beta.db"
export LIFE_INBOX_UPLOAD_DIR="/tmp/life_inbox_uploads"
export LIFE_INBOX_SESSION_SECRET="local-dev-secret-at-least-32-chars!!"
unset GEMINI_API_KEY
python3 -m pip install -r requirements.txt
python3 -m alembic upgrade head
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dev login:

```bash
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/dev-login \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","display_name":"You"}'
```

## Container / Postgres sketch

`docker-compose.yml` boots Postgres + the app image. It is for private
evaluation only. Before any shared beta:

1. Replace `LIFE_INBOX_SESSION_SECRET`
2. Keep `LIFE_INBOX_ALLOW_DEV_LOGIN=0`
3. Do **not** enable real Google OAuth until owner approval
4. Mount durable upload storage and database volumes
5. Take a backup before migrations

Install Postgres driver when using compose: `pip install 'psycopg[binary]'`
(or add to a private requirements overlay). The base `requirements.txt`
stays SQLite-friendly for local teaching.

## AI and embedding model (first run)

Two optional features need outside resources. The app works without either:
it falls back to keyword search, lexical related-item links and extractive
answers.

**Gemini (`GEMINI_API_KEY`)** powers analysis, Ask My Inbox synthesis and voice
transcription. Without a key, or when the API errors, each feature uses its
deterministic fallback. Set the key through the environment or a secrets store,
never in the image or the repo.

**Local embedding model** powers semantic search and "related" links
(`docs/semantic-linking.md`). `fastembed` downloads the model
(`BAAI/bge-small-en-v1.5`, a small ONNX file) from the Hugging Face hub the
first time it is needed, so:

- The first search or analysis after a fresh install needs outbound network
  access and some disk space, and is slower while the model downloads and loads.
- If the download fails, the app logs a warning and uses the fallbacks for the
  life of that process. It does not retry on every request, so fix the network
  and restart.
- The `Dockerfile` downloads the model at build time into `/opt/fastembed`
  (`FASTEMBED_CACHE_PATH`), so containers need no network for it at runtime.
  Building the image therefore needs access to the Hugging Face hub.
- By default the model is cached in the OS temp dir (`fastembed_cache`). In a
  container that is lost on restart, so the model downloads again. Point
  `FASTEMBED_CACHE_PATH` at a mounted volume to keep it.
- For air-gapped hosts, or to avoid a slow first request, warm the cache once
  with network access and ship that directory:

  ```bash
  FASTEMBED_CACHE_PATH=/data/fastembed python3 -c     "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5')"
  ```

- `LIFE_INBOX_DISABLE_EMBEDDINGS=1` turns the model off entirely. Changing
  `LIFE_INBOX_EMBEDDING_MODEL` means re-evaluating the 0.40 related-link cutoff.

Embeddings are computed on demand and cached in memory only; nothing about them
is stored in the database.

## Concurrency and database choice

- SQLite connections run in WAL mode with a 5 s busy timeout, so readers do not
  block the single writer and short write bursts queue instead of failing. WAL
  keeps `-wal` and `-shm` files next to the database: back up all three (or use
  `sqlite3 .backup`), and keep the file on a local disk, not a network share.
- SQLite still allows only one writer at a time. It suits a handful of active
  users; use Postgres (see the compose sketch) for more.
- At most `GEMINI_MAX_CONCURRENT` (default 4) Gemini requests run at once per
  process, so slow calls cannot occupy every server thread. A request that
  cannot get a slot within 20 s uses the normal fallback (keyword search,
  extractive answer, deterministic analysis, empty transcript).
- A user can have only one analysis running at a time (database-enforced).
  A second `POST /api/analyze` gets `409`; a run stuck in `running` for over
  10 minutes is treated as crashed and expired.

## Migrations / backups / rollback

- Alembic is the only schema owner: `alembic upgrade head`
- Backup SQLite file or Postgres dump **before** upgrading
- Rollback of data-bearing revisions is disabled by design; restore from backup
- Uploads live under `LIFE_INBOX_UPLOAD_DIR` (local filesystem backend)

## Security / readiness checklist

- [ ] Session secret is unique and long
- [ ] Dev login disabled outside local
- [ ] Google OAuth still stubbed (`/api/auth/google/start` → 501)
- [ ] Calendar writes still disabled
- [ ] User A cannot read/delete User B items (covered by tests)
- [ ] Health endpoint reports env + warnings
- [ ] No secrets committed; uploads/DBs gitignored
- [ ] Owner approval before public DNS / paid hosting / live OAuth

## What this milestone does **not** do

- Real Google sign-in / OAuth consent
- Object storage (S3) wiring
- Public internet deployment
- Purchases or paid managed services
