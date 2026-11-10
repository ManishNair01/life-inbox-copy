# Deploying Life Inbox in a container

Life Inbox runs as **three pieces**:
- the **web app** (`Dockerfile`; it runs the migrations, then serves);
- a **scheduler** (the same image, running `python -m app.notifications.scheduler`
  for notifications, Scout's weekly push and the weekly review);
- **Postgres**.

Uploaded files live on a **disk** mounted at `/data/uploads`.

There are two ways to run it. Both give you HTTPS.

| | A. A hosting platform (PaaS), e.g. Railway, Render or Fly.io | B. Your own small server (VPS) |
| --- | --- | --- |
| Effort | Least: the platform builds the `Dockerfile`, gives you Postgres and a web address with HTTPS | More: you look after the server, but everything is in one `docker compose` command |
| You need | An account on the platform; the code on GitHub (or the platform's command-line tool) | A server running Ubuntu, a domain (or subdomain) and SSH |
| Cost | Usually paid for an always-on service, a database and a disk: check the platform's prices | The server and the domain |

Screens and names differ a little between platforms; the settings below are
what matters.

---

## Free: share Life Inbox from your own PC (Tailscale Funnel)

No server to rent. Life Inbox keeps running on your PC as it does now, and
Tailscale Funnel gives it a public HTTPS link that stays the same, for example
`https://yourpc.your-name.ts.net`. Anyone with the link can open it, sign up
and use it **while your PC is on and Life Inbox is running**. Everyone's notes
are stored on your PC, each account kept separate.

1. **Install Tailscale:** `winget install --id Tailscale.Tailscale -e`, then
   answer its prompts.
2. **Sign in:** Tailscale icon in the taskbar → Log in, or run `tailscale up`.
   Use a free account; Google, GitHub or Microsoft sign-in all work.
3. **Share port 8000:**
   ```bash
   tailscale funnel --bg 8000
   ```
   The first time, it prints a link to turn on HTTPS and Funnel for your
   account: open it, allow, and run the command again. It then prints your
   public link.
4. **Keep it safe:**
   - `.env` has `LIFE_INBOX_SECURE_COOKIES=1`, so sign-in cookies only travel
     over HTTPS;
   - Life Inbox listens on 127.0.0.1 only, so the Funnel link is the only way
     in from outside;
   - keep a strong Windows password and back up `data/`.
5. **After a restart:** Tailscale starts with Windows. Start Life Inbox again
   (the `uvicorn` command in AGENTS.md "Startup").
6. **Stop sharing:**
   ```bash
   tailscale funnel reset
   ```

Things to know:
- New users start with AI off. Anyone who ticks "use AI" at sign-up, or later
  in Settings, uses your NVIDIA credits.
- Email is off: if someone forgets their password, reset it with
  `python -m scripts.reset_password --email them@example.com`.
- You are the operator of everyone's data on your PC: see "Before a public
  beta" in `docs/deployment.md`.

---

## Before either route (on your PC)

1. **Make the secrets** you'll paste into the host:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
   - that line gives `LIFE_INBOX_OTP_PEPPER`;
   - run it again for `POSTGRES_PASSWORD` (route B only);
   - your NVIDIA key is `NVIDIA_API_KEY` (copy it from the NVIDIA site; never
     commit it).
2. **Choose email:**
   - `LIFE_INBOX_EMAIL_PROVIDER=off` for a private beta. "Forgot password"
     says it isn't set up, and you reset a password with
     `python -m scripts.reset_password`.
   - `smtp` for real reset emails: for Gmail, turn on 2-step verification, make
     an **app password**, and use `smtp.gmail.com`, port `587`.
3. **Decide about your notes:** start fresh, or **move your current notes** (step
   B7 / A8, after the first deploy).

All the settings are listed, with comments, in `deploy/env.example`.

---

## Route A: a hosting platform

1. **Put the code on GitHub, in a private repository.** The docs and
   `decision.md` mention your real notes, so don't make it public without
   cleaning those first. `.gitignore` already keeps out `.env`, `data/*.db` and
   uploads.
2. **On the platform,** make a new project, then a service "from GitHub repo",
   and pick the repository. It finds the `Dockerfile`.
3. **Add a Postgres database** to the project. Copy its connection URL and set
   `DATABASE_URL` to it, written as `postgresql+psycopg://USER:PASSWORD@HOST:5432/DB`
   (the platform may write `postgres://…`; change the start to
   `postgresql+psycopg://`).
4. **Add a volume (persistent disk)** to the web service, mounted at
   `/data/uploads`.
5. **Set the web service's variables** from `deploy/env.example`:
   - `LIFE_INBOX_ENV=beta`, `LIFE_INBOX_TIMEZONE=Asia/Kolkata`;
   - `LIFE_INBOX_OTP_PEPPER`, `DATABASE_URL`, `LIFE_INBOX_UPLOAD_DIR=/data/uploads`;
   - `NVIDIA_API_KEY`;
   - `LIFE_INBOX_EMAIL_PROVIDER` (and the SMTP settings if `smtp`).

   The platform's `PORT` is picked up by itself.
6. **Deploy.** The logs show the Alembic migrations, then Uvicorn. Open the
   address the platform gives you:
   - `/api/health` should answer;
   - then `/` shows the sign-in page.
7. **Add a second service from the same repository** (a "worker" or
   "background" service):
   - start command: `python -m app.notifications.scheduler`;
   - the same variables;
   - no public port.
8. **Your notes:**
   - **Fresh:** create your account on the new site ("Create New Life").
   - **Moving them:** do it *before* signing up there. Use the database's
     *public* connection URL, from your PC:
     ```bash
     python -m scripts.copy_sqlite_to_postgres --to "postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB" --dry-run
     ```
     ```bash
     python -m scripts.copy_sqlite_to_postgres --to "postgresql+psycopg://USER:PASSWORD@HOST:PORT/DB"
     ```
     Then copy `data/uploads/` (your saved PDFs, images and audio: 8 files,
     about 3 MB today) into the volume, using the platform's shell or file
     tool. If it has none, the notes still have their text; re-upload the few
     files you need.
9. **Turn on the database's backups** on the platform.

---

## Route B: your own server (VPS) with `docker-compose.vps.yml`

1. **Get the server and the address:**
   - rent a small Ubuntu server (2 GB of memory is comfortable; OCR and builds
     like memory);
   - point your domain or subdomain's **A record** at its IP address.
2. **Install Docker** on it, over SSH:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. **Get the code there:**
   - `git clone` your private repository;
   - or copy the folder **without** `data/`, `.env` and `.venv`.
4. **Create the settings,** in the project folder:
   ```bash
   cp deploy/env.example .env
   ```
   Fill in `POSTGRES_PASSWORD`, `LIFE_INBOX_DOMAIN` (for example
   `inbox.yourname.in`), `LIFE_INBOX_OTP_PEPPER`, `NVIDIA_API_KEY` and the email
   choice. Leave `DATABASE_URL` empty: the compose file builds it.
5. **Start it:**
   ```bash
   docker compose -f docker-compose.vps.yml up -d --build
   ```
   Caddy gets the HTTPS certificate by itself; ports 80 and 443 must be open.
6. **Check it:** open `https://your-domain/api/health`, then
   `https://your-domain/`. The logs are at:
   ```bash
   docker compose -f docker-compose.vps.yml logs -f web
   ```
7. **Moving your notes** (before signing up there): copy your `data/life_inbox.db`
   and `data/uploads/` into the project folder's `import/` on the server, then:
   ```bash
   docker compose -f docker-compose.vps.yml run --rm -v "$PWD/import:/import" web sh -c 'python -m scripts.copy_sqlite_to_postgres --from sqlite:////import/life_inbox.db --to "$DATABASE_URL"'
   ```
   ```bash
   docker compose -f docker-compose.vps.yml cp import/uploads/. web:/data/uploads/
   ```
   Then delete `import/` from the server.
8. **Backups**, for example nightly:
   ```bash
   docker compose -f docker-compose.vps.yml exec -T db pg_dump -U lifeinbox lifeinbox > backup-$(date +%F).sql
   ```
9. **Updating later:** pull the new code, then run the same `up -d --build`.
   Migrations run on start; take a backup first.

---

## After deploying (both routes)

- **Resetting a password (email off):** on the platform's shell, or
  `docker compose … exec web`:
  ```bash
  python -m scripts.reset_password --email you@example.com
  ```
- **Before inviting anyone else:** publish a privacy / grievance contact on
  `/privacy` (India's DPDP Act), and have the draft privacy policy and terms
  reviewed.
- **Memory in filing** (`LIFE_INBOX_MEMORY_IN_FILING`) stays `0` until the
  memory replay is approved.
- **Cost:** with your NVIDIA key set, each account makes about 1 greeting call
  a day, 1 weekly review a week, plus filing and Ask me calls as at home.
  Users can switch AI off in Settings.
