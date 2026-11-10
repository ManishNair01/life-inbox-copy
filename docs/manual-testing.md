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

- [ ] App loads: composer on top; Home shows Captain, This week, Today's focus and
      Recently captured. Analyze and All notes are in Topics and spaces; tasks in Priority.
- [ ] Save a note → appears in Recently captured and in All notes
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

## Three-pane app smoke (change 009)

Check at about 1440×900 and at phone width (375 px).

- [ ] Each feature in the left panel opens its view, at the top of the view; Back returns
- [ ] Nothing scrolls the whole page on desktop; at 375 px nothing is wider than the screen
- [ ] Picking an area in the right panel shows "Viewing: <area> ×"; Home becomes its page;
      All notes, tasks, calendar, Timeline, search and pinned topics show only that area
- [ ] × in the header, picking the area again, or Captain shows everything again
- [ ] Dashboard, Attention, Ask and the AI-organized inbox say they aren't filtered yet
- [ ] Header search finds notes; with an area picked, "Search everything" clears it
- [ ] Clicking any note or task on Home opens the note page: breadcrumb, source, why it's
      here, tasks, related, Mark done, Move to topic, Show in All notes
- [ ] Move to topic: breadcrumb updates, "Moved to …" stays, "Why it's here" says you moved it
- [ ] Preview calendar on a task opens the dock at the bottom right; × closes it
- [ ] Account menu: Settings, Failed captures (shows only failed items), Export Markdown,
      Privacy, Change password, Sign out
- [ ] No console errors

## Topics and spaces smoke (change 010)

- [ ] Topics and spaces shows one card per life area, busiest first, packed into columns;
      empty topics faded; subtopics (↳) under their topic; "Add your own topic" fills a gap
- [ ] With an area picked, only its card shows
- [ ] + New topic → Next shows the suggestion with a life area you can change; a subtopic
      follows its parent; the status says where the topic went
- [ ] Clicking a topic opens its page: path, description, subtopic chips, notes (newest first),
      kind filters when it has more than one kind
- [ ] Rename: a name you already use is refused; a new name updates everywhere
- [ ] Move a topic of yours to another area (defaults and subtopics say why they can't)
- [ ] Delete a topic of yours: the confirmation says where its notes go; the summary shows after
- [ ] Pinned topics, Home's topic chips and the note page's path open the topic page

## Timeline, Calendar, Priority and Dashboard smoke (change 011)

- [ ] Timeline: Week | Month switch, ‹ › and Today; spikes solid/dashed, taller for High;
      "Undated: N" opens Priority with the backlog open
- [ ] Calendar: dots coloured by life area, dashed when unconfirmed; clicking a day opens
      its list as a pop-up (×, Esc and a click outside close it); a title opens the note
- [ ] Priority: High / Medium / Low columns show today and the next 3; the rest is in Backlog
- [ ] Drag a card to another column → "Your pick"; Analyze again → it stays; "Back to Life
      Inbox's" clears it; the picker on each card does the same without a mouse
- [ ] "No date · set" gives an undated task a date; Group by area; + Add task
- [ ] Dashboard: this week's numbers, busiest day in your time zone, attention bars,
      Captain noticed, growing and quiet topics, coming up; with an area picked, that area
- [ ] At phone width the columns stack and the day list opens from the bottom

## Capture from anywhere and hover cards smoke (change 011a)

- [ ] Only Home shows Quick Capture at the top; every other view starts with its own content
- [ ] "+ New note" in the header (or N) opens the composer as a panel; Esc, × or a click outside closes it
- [ ] Saving from the panel closes it, keeps you on the view, and shows "Saved… Open"; Open opens the note
- [ ] Phone width: a round "+" bottom-right away from Home; the composer opens from the bottom
- [ ] Hovering a topic shows its area, note count, description and subtopics
- [ ] Hovering a note shows its kind, the day it was saved, your note (sources) and its first lines

## Dates smoke (change 012, part 1)

- [ ] Click a task's date chip (Home, Timeline, Priority, Dashboard) → the picker shows its current date
- [ ] "A day later" / "A week later" (or "Tomorrow" / "Next week") saves in one click, even over a
      confirmed date; the Calendar and Timeline move; the message offers "Open note"
- [ ] The note page lists the change under "Updates"; the Calendar pop-up and task cards have "Postpone"
- [ ] Confirm a date, then edit the note's text to another date → the task moves and you're asked
      "Is that right? · Confirm · Change"; Confirm records "You confirmed …"
- [ ] Edit the note keeping the same date → it stays confirmed and nothing is asked
- [ ] "Analyze Entire Inbox" never moves a date you set or confirmed
- [ ] Export Markdown includes your note on sources and each note's "Updates"

## Dates smoke (change 012, part 2)

- [ ] "Dentist on 12 Nov" → a solid chip and on the Calendar; hovering says "From your note"
- [ ] "Call mom this weekend" → right after saving, a card in the middle of a dimmed page: "Is this
      the right day?" with the day as a calendar page and "Yes, Sat …"; until you answer, a dashed
      "…? · confirm" chip, dashed in Timeline, and NOT on the Calendar
- [ ] Yes → a green "✓ …" chip, on the Calendar; the note's Updates say "You confirmed …"
- [ ] A note with two guesses asks twice ("One more date to check after this")
- [ ] "Ask me later" (or Esc, or a click on the dim) → Captain's card on Home says "A date waits for
      your OK · Check it"; Check it asks again
- [ ] Typing in Quick Capture when the card appears: Enter doesn't answer it; Esc returns you to your text
- [ ] Edit a note's date words → the same card says "Your edit moved a date"

## Memory and secrets smoke (change 016)

- [ ] Move a note to another topic → `#/memory` (Captain's "What I learned ›") lists "You filed “…”
      under …" with "From a change you made" and "Open the note"
- [ ] Set a task's priority or date → "You set “…” to High priority." / "“…” is on …"
- [ ] Edit a fact → the box takes focus; Save → "Added by you"
- [ ] Delete → "Forget it for good?" with focus on Keep; Forget → gone, and never suggested again
- [ ] Health area page: "Remember health facts" is off; a gym priority change is not remembered;
      switch it on → it is; switch it off → asks first, then the health facts are gone
- [ ] Save "Flat wifi password: Hunter2Blue" → titles, Recent, All notes and search show
      "password: ••••"; the note page says it's hidden, with Show / Hide; closing hides it again
- [ ] With AI on: that note's filing makes no AI call (Settings → AI calls log, or the note page says
      "Filed without AI")
- [ ] Export Markdown → ends with "What Life Inbox learned about you"

## Ready-for-beta smoke (changes 024–025)

- [ ] Create New Life (sign-up): the "use AI" box starts unticked; after sign-up the app opens "Create
      New Life"; answers show on the memory page as "About you"; Skip for now goes Home
- [ ] Settings → AI processing: with it off, saving a note makes no AI call (AI calls log) and the note
      page says "Filed without AI"; switching on works again
- [ ] Settings → Delete my account: a wrong password or anything but DELETE deletes nothing; with both
      right, you're signed out and the sign-in page says the account was deleted (test account only!)
- [ ] /privacy and /terms: the AI switch, deletion, GDPR and DPDP rights

## Better sources smoke (changes 021–023)

- [ ] Without Tesseract: save a screenshot → it saves; the description says "Text in images isn't read
      yet: Tesseract isn't installed …"
- [ ] With Tesseract (`winget install --id UB-Mannheim.TesseractOCR -e`): a screenshot with text →
      its words under Source; a photo with no text and no note (with AI) → an AI description, marked
      as AI
- [ ] A PDF with formulas → the note page keeps one line per line
- [ ] A scanned PDF with Tesseract → "[Page N, read by OCR]" text; without → "image-only … Tesseract"
- [ ] A long PDF (6+ pages, with AI) → "Summary of the whole document (AI, made once …)"
- [ ] A saved link/PDF/image → Edit note (or Add a note) → Save → "Saved. Filed again from your words."

## Weekly review smoke (change 020; needs AI)

- [ ] Home shows a one-line AI greeting under "Good morning" after the first load of the day (code's
      summary line until then); reloading doesn't make another call (AI calls log)
- [ ] An area page's summary line is written by AI after the first visit; it stays the same until a
      note or task in that area changes
- [ ] After a week (or set `last_weekly_review_at` back on a test database): 3+ notes in one area
      sharing a word no topic covers → Captain: "A new topic? … Create it / Rename / Not now / Don't
      suggest this"; Create → the topic with its notes, and "Suggested by the … bot from note #… ;
      approved by you on …" on its page
- [ ] "Is this right? … Yes / No / Edit" for a fact the review suggests; Edit opens it on the memory page
- [ ] With the AI switch off (025) or no key: no greeting line, code's summaries, no review

## Ask me v2 smoke (change 019)

- [ ] "What do I have this week?" → your tasks for Mon–Sun, a guessed date marked "date not
      confirmed", and "Confirm … for …?" buttons; nothing changes until you tap one
- [ ] "What is the capital of France?" → "I couldn't find that in your notes, so I won't guess."; How I
      answered says "no AI call"
- [ ] With an area picked in the right pane → How I answered says "Asked only … (your lens)"
- [ ] A question about something you confirmed in memory → "From what Life Inbox remembers", with
      its note
- [ ] With AI: How I answered shows "1 AI call" (2 if a citation had to be repaired)

## Scout smoke (change 018)

- [ ] A task dated yesterday → the right pane's Scout says "1 quick question"; Scout asks "It was on …
      Did you do it?"; Done → "Captain updated the … bot's memory: …: done."
- [ ] Not yet, new date → the date picker; the pick → "Captain noted it: …: moved to …"
- [ ] Drop it → "Why drop it? (optional)" with three quick reasons; a reason drops it
- [ ] Sunday after 19:00 (or your Settings time) → "Let's tidy up: N quick questions", with undated
      tasks waiting 14+ days; Done for now → none until next week
- [ ] Tidy up in one go → "Snooze N past tasks to next week? Yes, move N" → next Monday
- [ ] Someday → off the Calendar and Timeline; Priority › Someday lists it; Back to my list
- [ ] Timeline shows ✓ on the day you completed a task
- [ ] A task at a set time has no "Remind me tomorrow"; others do (the date stays)

## Memory in filing smoke (change 017; needs AI and `LIFE_INBOX_MEMORY_IN_FILING=1`)

- [ ] Confirm "You run your college's events"; save "Finalise the stall list by Thursday" → Work &
      career; the note page says "It also used what it remembered: “You run your college's events”"
- [ ] Give "Dentist appointment" a date; save "Dentist moved to Friday 4pm" → no second dentist task;
      Captain asks "Did a plan move?"; Yes → the task is on Friday 16:00, confirmed
- [ ] "No, it's a different one" → the note gets its own task
- [ ] Without the flag: no "What Life Inbox knows" in the prompt (the AI calls log size is smaller)

## Thought-to-action smoke (change 014a)

- [ ] "I should probably call Rahul about our Jaipur trip" → no task; Captain asks "Make this a task?"
- [ ] "…a dhaba I want to visit next time I'm on that route" → no task, no date question; the note page
      shows it under "Ideas, not tasks yet" with Add as task
- [ ] "Pay rent by 5th" → a task straight away

## Smart link capture smoke (change 015)

- [ ] Save a YouTube link → the note's title is the video's exact title; the note page shows
      "Video · read from the page, not by AI" with the channel; no picture or player loads
- [ ] Save a recipe page → its ingredients and steps on the note page
- [ ] Save a link with `?utm_source=…` → it's stored without it
- [ ] Save the same link again (no note) → "You saved this link before… (no AI call)"
- [ ] Save it again with a new note → it's filed again for your note
- [ ] A page that gives almost nothing → "Limited preview: only the title could be read"

## Filing v2 smoke (change 014)

- [ ] Save "Buy Crocin and cough syrup" → Medicines & doctors; the note page says "Rule R1 · Filed …"
- [ ] Save something no rule fits → "Which topic? Life Inbox wasn't sure…" in Needs you, no topic,
      "Waiting for you" in Recently captured; a pick files it
- [ ] New accounts have no "Personal / Reference"
- [ ] Create a topic → "Moved N notes into … · Undo" only for notes that fit; Undo puts them back
- [ ] "Re-sort everything" says how many notes and AI calls first; the second click runs it
- [ ] With AI: a voice note takes 2 calls; the note page shows the tidied transcript as AI output
- [ ] "Pay rent by 5th" → a suggested date (the next 5th) waiting for your OK

## Captain's "Needs you" smoke (change 013)

- [ ] Home's Captain card shows up to 5 question cards; the greeting and Captain's badge count them all
- [ ] A guessed date → "A date to check"; Check it opens the date question; Yes removes the card
- [ ] "Not now" removes a card for good (reload: it stays gone)
- [ ] A capture that couldn't be read → Retry / Add a note / Delete; Add a note files it from your
      words; Delete asks "Yes, delete" first
- [ ] A note in Personal / Reference → "Which topic?" with its likeliest topics; a pick files it
- [ ] "Call the plumber" (no date) → Set date / Drop it
- [ ] Two dated tasks within an hour → "Two things at once"; Check opens that week's Timeline
- [ ] A topic with no life area → the five areas; a pick moves it
- [ ] A note never shows two questions at once; the second appears after you answer the first
- [ ] A date chip opens the month picker: the suggestion has a dashed ring; pick a day, "Add a time",
      Save; Esc closes it; from the question's Change it opens in the middle; on a phone, from the bottom
- [ ] Priority: a Low or Medium task due today or tomorrow sits one column higher with "↑ Due soon";
      choosing its priority yourself removes the raise
- [ ] A note saying "tomorrow" keeps its day when filed again on a later day

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

## Image capture smoke (Milestone 3C+)

- [ ] Choose a PNG/JPEG → item appears with `item_type=image`
- [ ] Thumbnail preview and **Open image** link work
- [ ] OCR (extracted) and AI description (inferred) are labeled separately
- [ ] **Edit OCR text** saves corrected extracted text without changing AI description
- [ ] Retry on failed image succeeds when the file is readable
- [ ] Analyze inbox includes ready image items (after OCR text or description exists)
- [ ] Non-image upload rejected with a clear message

## Voice capture smoke (Milestone 3D+)

- [ ] Upload a short wav/webm → item appears with `item_type=voice`
- [ ] Audio player works from the item card
- [ ] Transcript empty or placeholder when transcription is unconfigured
- [ ] **Edit transcript** saves text and analyze includes the voice item
- [ ] Optional: Record → Stop uploads a browser recording (mic permission required)
- [ ] Retry on failed voice processing succeeds
- [ ] Non-audio upload rejected with a clear message

## URL capture smoke (Milestone 3A+)

- [ ] Paste a public https URL → item appears with `item_type=url`
- [ ] Processing reaches `ready` with title + extracted text (or `failed` with error)
- [ ] Retry on failed URL succeeds when upstream recovers
- [ ] Analyze inbox includes ready URL items
- [ ] Private/local URLs (127.0.0.1, localhost) rejected before fetch

## Login / multi-user smoke (Milestone 7+)

- [ ] Opening `/` while signed out redirects to `/login`; no inbox content is shown
- [ ] Create account with email A (password 10+ chars, 18+ and Terms ticked); lands in inbox
- [ ] Mismatched confirm password and short password show clear errors
- [ ] Create a note; Sign out returns to `/login`; browser Back does not show the note
- [ ] Wrong password shows "Incorrect email or password."; correct password signs in and the note is there
- [ ] Create account B; note from A is not visible; delete of A’s id returns 404
- [ ] Change password: wrong current password rejected; after success old password fails, new works
- [ ] "Sign out everywhere" signs out another browser that was signed in
- [ ] Five wrong passwords lock sign-in for 15 minutes
- [ ] Forgot password: request a code; it prints in the server terminal (console mode)
- [ ] Wrong code shows attempts left; correct code + new password signs you in
- [ ] After reset the old password fails, other devices are signed out, the code can't be reused
- [ ] Requesting a second code within 60 s is refused; only the newest code works
- [ ] `/api/health` returns status + environment metadata
- [ ] Spoofing `X-User-Id` does not change ownership

## Attention / Calendar smoke (Milestone 5+)

- [ ] After analysis, Attention section shows Today / Upcoming / Overdue / Unscheduled
- [ ] Daily briefing summary and suggested focus appear
- [ ] Confirm date on a timed task; original phrase preserved; due_on normalized
- [ ] Snooze 1 day moves task into Snoozed bucket
- [ ] Preview calendar shows provider notes and requires explicit confirm
- [ ] Confirm (mock) records a local receipt; `/api/calendar/status` shows writes_enabled=false
- [ ] With `LIFE_INBOX_CALENDAR_PROVIDER=google`, confirm returns blocked (no OAuth/writes)

## In-App Calendar smoke (Milestone 8+)

- [ ] Month grid renders in the Calendar view with controls: Previous (`<`), Next (`>`), and Today.
- [ ] Days with scheduled items display visual event dots or count pills.
- [ ] Undated items do NOT appear on the calendar.
- [ ] Clicking any day (with or without events) selects it and updates the Day Details panel.
- [ ] Empty state renders cleanly when selecting a day with 0 events ("No events scheduled for this day").
- [ ] Event cards display title, source type badge (`text`, `voice`, `url`, `pdf`, `image`), and priority chip.
- [ ] Clicking "View source note" opens that note's page (change 009).
- [ ] Guessed dates ("by next Friday") are not on the calendar until confirmed from their date chip (change 012).
- [ ] Confirming a guessed date puts it on the calendar immediately.
- [ ] Completed tasks display struck through with a `✓ Completed` badge; dismissed tasks are hidden.
- [ ] Adding a new note with a date (e.g. "Dentist on 3 Nov") automatically updates the calendar without manual page refresh.
- [ ] Editing or deleting a dated note immediately updates or removes the calendar event.
- [ ] Keyboard navigation: Arrow keys move selection across days/weeks; Enter selects the day.

## Task notification smoke

Requires VAPID keys, HTTPS (or localhost), a browser with Web Push support,
and the minute scheduler (`python -m app.notifications.scheduler` locally or
the Compose `notifications` service). Tests must mock push; never send live
notifications from automated tests.

- [ ] Sign in, opt in under **Task notifications**, grant browser permission,
  and save a daily time and IANA timezone.
- [ ] After sign-in with notifications off, the prominent **Turn on task
  notifications** prompt appears. Its button requests browser permission only
  after the user clicks; if site permission is blocked, the prompt explains
  how to allow it in browser site settings.
- [ ] Reload and verify preferences persist; disable and re-enable notifications.
- [ ] Add an open task due today; at/after the chosen local digest time it
  appears in one daily push only.
- [ ] Verify overdue and completed tasks are not included in the digest.
- [ ] Enable the unscheduled prompt and verify only a count is shown; no date
  or time is assigned to undated tasks.
- [ ] An AI-linked High task with confirmed/clear date and explicit time gets
  an alert one hour before; manual High tasks, date-only tasks, and ambiguous
  unconfirmed timing do not.
- [ ] Verify browser permission denial and missing server VAPID configuration
  produce a clear status and do not enable notifications.
- [ ] Test with two accounts and confirm subscriptions, settings, and task
  delivery remain owner-scoped.

## Pagination regression (delete + Load more)

Automated coverage: `tests/test_pagination_state.py` (pure JS helper via Node).

Browser procedure (temp DB only):

1. Create notes “Pagination note 001” … “Pagination note 102” (102 notes).
2. Reload http://127.0.0.1:8000 — first 100 appear; “Load more” visible.
3. Delete “Pagination note 001”.
4. Click “Load more”.
5. Confirm notes 002–102 each appear exactly once (including 101); ID order.
6. Rapid double-click “Load more” on a >200-note inbox — no duplicates/skips;
   button disables while a list request is in flight.
7. Force a failed append (stop server, click Load more) — friendly error;
   already-displayed notes remain.
8. Failed delete (stop server, delete) — note stays visible; pagination unchanged.
9. Search / filters / Clear / create note / Back / Forward still reload from
   offset 0. Editing a note does not skip or duplicate pages.

## Error states

- [ ] Stop the server mid-request → friendly client error, text preserved in textarea
- [ ] Analyze with empty inbox → empty_inbox mode, no crash
- [ ] Failed “Load more” → friendly error; notes already on screen kept

## Do not

- Point `DATABASE_URL` at a real personal inbox database
- Commit API keys or generated `.db` files
