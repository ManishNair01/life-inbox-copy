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

## Ask My Inbox smoke (Milestone 4+)

- [ ] Save notes mentioning a specific topic (book, renewal, restaurant)
- [ ] Ask a matching question → answer cites the correct item(s)
- [ ] Ask an unrelated factual question → insufficient evidence message, no citations
- [ ] Citation “Open source” opens URL or PDF preview where available
- [ ] `GET /api/search?q=...` returns ranked excerpts

## PDF capture smoke (Milestone 3B+)

- [ ] Choose a small text-based PDF → item appears with `item_type=pdf`
- [ ] Processing reaches `ready` with title + extracted preview (or `failed` with error)
- [ ] “Open PDF” link downloads/previews the stored file
- [ ] Retry on failed PDF succeeds when the file is readable
- [ ] Analyze inbox includes ready PDF items
- [ ] Non-PDF or empty/image-only PDF rejected or marked failed with clear message

## URL capture smoke (Milestone 3A+)

- [ ] Paste a public https URL → item appears with `item_type=url`
- [ ] Processing reaches `ready` with title + extracted text (or `failed` with error)
- [ ] Retry on failed URL succeeds when upstream recovers
- [ ] Analyze inbox includes ready URL items
- [ ] Private/local URLs (127.0.0.1, localhost) rejected before fetch

## Error states

- [ ] Stop the server mid-request → friendly client error, text preserved in textarea
- [ ] Analyze with empty inbox → empty_inbox mode, no crash

## Do not

- Point `DATABASE_URL` at a real personal inbox database
- Commit API keys or generated `.db` files
