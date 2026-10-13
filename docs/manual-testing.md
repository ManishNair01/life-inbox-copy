# Manual testing / browser smoke checklist

Use a **temporary** database only.

```bash
export DATABASE_URL="sqlite:////tmp/life_inbox_manual.db"
unset OPENAI_API_KEY
python3 -m alembic upgrade head
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000

## Core smoke (Milestone 1+)

- [ ] Home page loads with capture box, analyze button, tasks, notes
- [ ] Save a note → appears under Raw saved notes
- [ ] Edit a note → text updates; analysis status becomes stale if prior analysis existed
- [ ] Delete a note → removed; linked orphan task disappears after analyze+delete
- [ ] Analyze Entire Inbox → buckets, todos, priority view, mode shown
- [ ] Reload page → latest analysis restored; tasks persist
- [ ] Complete / dismiss / reopen a task; filter by status
- [ ] Re-analyze after completing a task → task status unchanged
- [ ] Search/filter notes; Clear resets filters
- [ ] With >100 notes, “Load more” appears and appends
- [ ] After editing inbox post-analysis, stale banner / status appears
- [ ] Invalid empty note rejected with friendly status
- [ ] `/api/health` returns `{"status":"ok"}`

## Organization smoke (Milestone 2+)

- [ ] Dashboard shows Topics, High Priority, Open Tasks, Recently Captured, Needs Review, Related
- [ ] Add a custom topic from the Topics form
- [ ] Multi-action note creates multiple tasks from one source
- [ ] Confirm date on a task → labeled confirmed; survives re-analyze
- [ ] Near-duplicate notes appear under Related Items; dismiss removes them from the active list
- [ ] `PATCH /api/items/{id}/insight` user title/topic/priority survives re-analysis

## Error states

- [ ] Stop the server mid-request → friendly client error, text preserved in textarea
- [ ] Analyze with empty inbox → empty_inbox mode, no crash

## Do not

- Point `DATABASE_URL` at a real personal inbox database
- Commit API keys or generated `.db` files
