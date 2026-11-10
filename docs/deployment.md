# Deployment guide (private beta foundation)

This milestone adds a **minimum responsible** multi-user beta foundation.
It intentionally stops before paid infra, real Google OAuth consent, or
public production deploy unless an owner explicitly authorizes those steps.

## Environments

| Env | DB | Auth | Notes |
| --- | --- | --- | --- |
| `local` (default) | SQLite | Email + password; no anonymous access | Temp DBs for agents/tests |
| `beta` | PostgreSQL required | Email + password; `Secure` cookies + HSTS | Server-side sessions |
| `production` | PostgreSQL required | Same as beta | Not enabled in this teaching build |

## Required environment variables

```bash
LIFE_INBOX_ENV=local|beta|production
DATABASE_URL=sqlite:////tmp/life_inbox.db   # or postgresql+psycopg://...
LIFE_INBOX_UPLOAD_DIR=/data/uploads
LIFE_INBOX_AUTH_MODE=password
LIFE_INBOX_EMAIL_PROVIDER=console   # local: emails (reset codes) print in the server terminal
LIFE_INBOX_OTP_PEPPER=<32+ random chars>   # required in beta/production
LIFE_INBOX_TIMEZONE=UTC   # your users' zone, e.g. Asia/Kolkata: "today"/"tomorrow" in notes are read in it
LIFE_INBOX_MEMORY_IN_FILING=0   # 1 sends memory hints with each filing call (change 017); off until the replay is OK
LIFE_INBOX_TESSERACT_CMD=        # optional: full path to tesseract(.exe) if it isn't on PATH (change 021)
LIFE_INBOX_VISION_MODEL=         # optional: the model for image descriptions (change 021)
LIFE_INBOX_MAX_UPLOAD_MB=5
LIFE_INBOX_CALENDAR_PROVIDER=mock|google
# Optional Sign in with Google (button hidden when unset). In beta/production the
# redirect URI must be https and registered in the Google Cloud OAuth client.
GOOGLE_CLIENT_ID=<oauth client id>
GOOGLE_CLIENT_SECRET=<oauth client secret>
GOOGLE_REDIRECT_URI=https://your-domain/auth/google/callback
# Real email (password reset codes): LIFE_INBOX_EMAIL_PROVIDER=smtp, then
LIFE_INBOX_SMTP_HOST=smtp.gmail.com
LIFE_INBOX_SMTP_PORT=587          # 465 = SSL
LIFE_INBOX_SMTP_USER=you@gmail.com
LIFE_INBOX_SMTP_PASSWORD=<gmail app password>
LIFE_INBOX_SMTP_FROM=you@gmail.com
LIFE_INBOX_VAPID_PUBLIC_KEY=<URL-safe base64 public key>
LIFE_INBOX_VAPID_PRIVATE_KEY=<URL-safe base64 private key>
LIFE_INBOX_VAPID_SUBJECT=mailto:admin@example.com
```

Optional AI (never in automated tests): `NVIDIA_API_KEY` (default provider),
with `NVIDIA_LLM_MODEL`, `NVIDIA_ASR_MODEL` and `NVIDIA_BASE_URL`; or
`OPENAI_API_KEY` with `OPENAI_MODEL`. `LIFE_INBOX_AI_TIMEOUT_SECONDS`
(default 60) limits how long a text request may take; speech-to-text allows
180 seconds. Every request is counted in the `ai_calls` table.
Optional: `OPENAI_API_KEY` for live organization only (never in automated tests).
VAPID keys are required for Web Push. Keep the private key in `.env` locally or
in the deployment secret store; never commit it. Generate a fresh P-256 pair
with the installed `pywebpush` dependency and retain the displayed private key:

```bash
python -c "import base64; from py_vapid import Vapid; from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat; v=Vapid(); v.generate_keys(); enc=lambda b: base64.urlsafe_b64encode(b).decode().rstrip('='); print('LIFE_INBOX_VAPID_PUBLIC_KEY='+enc(v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))); print('LIFE_INBOX_VAPID_PRIVATE_KEY='+enc(v.private_key.private_numbers().private_value.to_bytes(32, 'big')))"
```

The public key is returned to opted-in browsers. The private key must remain
server-side. A key change requires users to subscribe again in their browser.

## Local run

```bash
export DATABASE_URL="sqlite:////tmp/life_inbox_beta.db"
export LIFE_INBOX_UPLOAD_DIR="/tmp/life_inbox_uploads"
unset OPENAI_API_KEY
python3 -m pip install -r requirements.txt
python3 -m alembic upgrade head
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000 — you are sent to `/login`. Create an account
(email + password, 18+ and Terms confirmation), then you land in your inbox.

From the command line:

```bash
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a long passphrase here","display_name":"You","confirm_adult":true,"accept_terms":true}'
curl -b cookies.txt http://127.0.0.1:8000/api/items
```

### Forgot password

On `/login`, **Forgot password?** asks for the email and sends a 6-digit
code (valid 10 minutes, single use, 5 wrong tries, max 5 codes per hour).
In local console mode the "email" is printed in the terminal running the
server — copy the code from there. Beta/production refuse to start with
`console`; use `LIFE_INBOX_EMAIL_PROVIDER=smtp` (see the variables above) for real delivery.

Operator fallback (no email needed), e.g. for old dev-login accounts:

```bash
python3 -m scripts.reset_password --email you@example.com
```

### Existing data from before password login

Data captured anonymously before Milestone 7 belongs to the built-in
`local@life-inbox.local` user, which cannot sign in. Register your account,
then move that data into it:

```bash
python3 -m scripts.claim_local_owner --to-email you@example.com --dry-run
python3 -m scripts.claim_local_owner --to-email you@example.com
```

## Container / Postgres sketch

`docker-compose.yml` boots Postgres + the app image. It is for private
evaluation only. Before any shared beta:

1. Serve over HTTPS only (session cookies are `Secure` in beta/production)
2. Mount durable upload storage and database volumes
3. Take a backup before migrations

The Compose `notifications` service checks once per minute. Set the VAPID
variables in the root `.env` before enabling notifications. Outside Compose,
run `python -m app.notifications.dispatcher` from a deployment scheduler every
minute. The local scheduler and dispatcher load `.env` when started from the
project root. The worker uses the same database and VAPID secret values as the web
app; do not run multiple independent workers unless they share the database
delivery ledger.

In the browser, open **Task notifications**, opt in, and choose the daily
digest time and IANA timezone. Push requires HTTPS (localhost is allowed for
development) and browser notification permission. The digest contains open
tasks due on the user's local date; overdue tasks remain in Attention and are
not repeated in pushes. AI-linked High-priority tasks get an additional alert
only when a date and explicit time are known and the timing is not awaiting
confirmation. Date-only and undated tasks receive no invented times. The
optional unscheduled prompt is a count-only planning reminder.

Install Postgres driver when using compose: `pip install 'psycopg[binary]'`
(or add to a private requirements overlay). The base `requirements.txt`
stays SQLite-friendly for local teaching.

## Migrations / backups / rollback

- Alembic is the only schema owner: `alembic upgrade head`
- Backup SQLite file or Postgres dump **before** upgrading
- Rollback of data-bearing revisions is disabled by design; restore from backup
- Uploads live under `LIFE_INBOX_UPLOAD_DIR` (local filesystem backend)

## Security / readiness checklist

- [ ] HTTPS in front of the app (cookies are `Secure`, HSTS is sent)
- [ ] Logged-out requests get 401 / redirect to `/login` (covered by tests)
- [ ] Draft `/privacy` and `/terms` pages replaced with lawyer-reviewed text
- [ ] Calendar writes still disabled
- [ ] User A cannot read/delete User B items (covered by tests)
- [ ] Health endpoint reports env + warnings
- [ ] No secrets committed; uploads/DBs gitignored
- [ ] Owner approval before public DNS / paid hosting / live OAuth

## What this milestone does **not** do

- Real email delivery, SMS codes, email verification at sign-up, account
  export or deletion (planned in `docs/production-auth-plan.md`)
- Object storage (S3) wiring
- Public internet deployment
- Purchases or paid managed services

## Reading text in images (OCR, change 021)

Life Inbox reads text in screenshots and photos with **Tesseract**, on the same
computer. Until it's installed, image notes still save; the note page says
"Text in images isn't read yet: Tesseract isn't installed".

- **Windows**: `winget install --id UB-Mannheim.TesseractOCR -e`. Life Inbox
  finds it in `C:\Program Files\Tesseract-OCR\`; elsewhere, set
  `LIFE_INBOX_TESSERACT_CMD` to the full path of `tesseract.exe`.
- **macOS**: `brew install tesseract`. **Debian/Ubuntu**: `sudo apt install tesseract-ocr`.
- **Check**: `tesseract --version`, then save a screenshot with text; its words
  show under "Source" on the note page.
- The Python side (`pytesseract`, `Pillow`) is in `requirements.txt`.
- `LIFE_INBOX_DISABLE_OCR=1` turns OCR off.

**The vision call (decision O)**: an image with no readable text and no note of
yours gets one AI description. The model is `LIFE_INBOX_VISION_MODEL`, else
`meta/llama-3.2-11b-vision-instruct` on NVIDIA NIM or `gpt-4o-mini` on OpenAI.
`LIFE_INBOX_DISABLE_VISION=1` turns it off.

## Background AI work and the scheduler (changes 018, 020)

`python -m app.notifications.scheduler` (once a minute) sends due notifications, Scout's weekly
catch-up push, and runs each user's weekly review when it's due. Without the scheduler, the weekly
review runs after a user's first visit once 7 days have passed, and the daily greeting and area
summaries are written in the background after a page asks for them. None of it runs for a user whose
AI switch is off.

## Before a public beta (change 025)

- Publish a grievance / privacy contact on `/privacy` (required by India's DPDP Act).
- Have the privacy policy and terms reviewed; they're marked "draft".
- Decide how long database backups are kept; the policy says deleted accounts may remain in backups
  until they are replaced.

## Deploying in a container

Step-by-step, for a hosting platform or your own server: `docs/deploy-container.md`. The files it
uses:
- `Dockerfile`: Tesseract and ffmpeg included; it honours `$PORT` and runs the migrations first;
- `docker-compose.vps.yml` + `deploy/Caddyfile`: one server with automatic HTTPS;
- `deploy/env.example`: every setting, with no secrets;
- `scripts/copy_sqlite_to_postgres.py`: moving existing notes.

