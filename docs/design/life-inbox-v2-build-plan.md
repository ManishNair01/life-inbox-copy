# Life Inbox v2: build plan

**Status:** Plan for review. Nothing in it is built yet.
**Date:** 2026-11-02
**What it builds:** the design in `docs/design/life-inbox-v2-design.md`, the
five life areas from `docs/research-life-categories.md`, and the decisions in
`decision.md`, including our discussion of LLM calls and memory.
**Starting point:** changes 001–005 are built but not pushed. The full test
suite is green (229 tests).

---

## 1. How every change is built

Every change follows the routine used for 001–005 (AGENTS.md):

1. **Read `AGENTS.md` first**, and log each decision in `decision.md` while
   working.
2. **Tests** use temporary SQLite databases, sign in through
   `tests/auth_helpers.py`, and **mock every AI call**. Tests never call NVIDIA.
3. **Schema changes go only through Alembic.** Each migration is tested from an
   empty database and from a synthetic database at the previous version.
4. **The full test suite is green** before a change counts as done.
5. **Browser check on a throwaway database** (port 8018, checking
   `location.host` before acting), never on your own app at port 8000.
6. **Your database:** back it up to
   `data/life_inbox.backup-<date>-pre-<migration>.db`, run
   `python -m alembic upgrade head`, then restart your server.
7. **A change document** `docs/changes/NNN-….md` (problem, solution, files,
   tests, verification, before pushing), plus a row in `docs/changes/README.md`.
8. **No push.** Everything waits for your review (§9).

Rules for every change:

- Every new route needs a signed-in user and only sees that user's data
  (`owner_user_id`). There is no anonymous fallback.
- Your words, source text, AI output and values you confirmed are stored
  separately.
- Outside actions (calendar writes, messages) happen only after you tap to
  confirm.
- The stack stays the same: FastAPI, SQLAlchemy, Alembic, vanilla JS. No React
  or Vue, and no vector database unless the replay test (§7) shows word search
  isn't enough.
- No secrets, databases or uploads in the diff.
- When a change adds a module, update the boundaries in `AGENTS.md` and
  `docs/architecture.md`.

---

## 2. Where we start

**Built, not pushed:**

- 001: the 2,000-character limit.
- 002: topics with descriptions and subtopic suggestions.
- 003: deleting topics.
- 004: the topic-name fix and per-user topics.
- 005: one composer, with your note on sources.

**Problems going in**, each fixed by a change below:

| Problem today | Fixed in |
|---|---|
| Ask My Inbox got NVIDIA "404 not found" and fell back to its basic answer | 006 |
| AI calls are made in four separate places, with no count and no size limit | 006 |
| The privacy policy names OpenAI, not NVIDIA, and doesn't mention link fetching | 007 |
| Nine v1 built-in topics, including a catch-all | 008, 014 |
| One long scrolling page; nothing links to anything | 009–011 |
| "Coming saturdy" never becomes a date | 012, 014 |
| "Analyze Entire Inbox" sends every note, in full, in one call | 014 |
| Creating a topic re-analyses the whole inbox | 014 |
| Voice notes use three model calls | 014 |
| Offline mode makes tasks from a source's own text ("Amount payable…") | 014 |
| YouTube links save a cut-off summary plus footer text | 015 |
| No memory, no catch-up, and a basic Ask | 016–020 |
| Image text isn't read (no OCR); PDF formulas and scans aren't read | 021, 022 |
| Your note on a saved source can't be edited | 023 |

---

## 3. Decisions needed, and when

| # | Decision | Needed before | Recommendation |
|---|---|---|---|
| A | Push 001–005 now, or together with v2? | 006 | Now. Teammates keep changing the repo, so a smaller push is easier to review and merge. |
| B | Visual style: the calm palette from the design, or the team's dark neo-brutalist theme | 009 | A team decision. The new app uses colour variables either way, so the theme can be switched. |
| C | Where search, the full notes list and Markdown export go. v1 has them; layout A has no place for them yet. | 009 | A search box in the header (it follows the lens), an "All notes" card in Topics and spaces with today's filters, and Export in the account menu. |
| D | Multi-bot lens: now or later? | 009 | Later. Build the API so it can accept more than one bot. |
| E | Priority scheme: High/Medium/Low, or urgent/important? | 011 | High/Medium/Low, as in the prototype and today's data. |
| F | Timeline history: show completed ✓ on past days? | 011 | Yes, once Scout (018) records outcomes. |
| G | Batching: notes saved while a call is running go together in the next call (up to 5), instead of waiting a fixed 30 seconds | 014 | Yes. The first note is then never delayed. |
| H | Links: a free YouTube Data API key (full description, duration, chapters), or oEmbed only? Transcripts stay out for now. | 015 | oEmbed first; add the key if titles aren't enough. |
| I | Link pictures and players: show no YouTube images at all, or YouTube's privacy-enhanced player behind a click? | 015 | Text only at first. |
| J | Which notes count as secrets (passwords, PINs, wifi keys)? | 016 | Review the detection list in 016. |
| K | Scout's name: Scout, Recap or Check-in? | 018 | Your choice. |
| L | Weekly catch-up default: Sunday evening? | 018 | Your choice. |
| M | When you drop a task, should Scout ask why (optional)? | 018 | Your choice. |
| N | Captain's Home greeting: a code template (0 calls) or written by the AI (1 a day, saved)? | 020 | Your choice. |
| O | Images with no readable text and no note: one extra AI call to describe them, or none? | 021 | Your choice. |
| P | Long PDFs: a one-time AI summary when saved (+1 call per PDF), or the first part only? | 022 | Your choice. |
| Q | The AI-processing switch. The auth plan (§7) has it off by default, opted into at registration. | 025 | Your choice. |

---

## 4. The order at a glance

| Phase | Changes | What you can try at the end |
|---|---|---|
| 1. Foundations | 006 · 007 · 008 | Ask works again, the privacy page names NVIDIA, and your topics sit under the five areas |
| 2. The new app | 009 · 010 · 011 | The three-pane app: lens, note page, Topics and spaces, Timeline, Calendar, Priority, Dashboard |
| 3. Captain and filing | 012 · 013 · 014 · 015 | The date picker, Needs you, one-call filing with rules and reasons, and clean link cards |
| 4. Memory | 016 · 017 | "What I learned about you", and filing that uses memory |
| 5. Helpers | 018 · 019 · 020 | Scout catch-up, Ask me v2, and the weekly review with topic proposals and bot summaries |
| 6. Better sources | 021 · 022 · 023 | Text read from images, PDF formulas and scans, editing your note on a source |
| 7. Ready for beta | 024 · 025 | Onboarding questions and the privacy pass, then the push |

At the end of each phase you try it, and we fix what you find before the next
phase starts.

---

## 5. The changes

### Phase 1: Foundations

#### 006: One path for every AI call, and fix Ask's 404

**Why:**
- AI clients are created in four places: `app/organizer.py` twice,
  `app/retrieval/ask.py`, and `app/capture/voice_extract.py`.
- None of these calls is counted or size-limited.
- Ask failed with NVIDIA "404 not found".

**Build:**
- One small module that every AI call goes through (proposed: `app/llm.py`).
  It handles:
  - the client and model, taken from `.env`;
  - a timeout;
  - a size check against the limits in §6;
  - the single repair retry and one shared fallback rule;
  - a count of calls.
- A call log table: owner, action (file, ask, weekly…), model, outcome, prompt
  size and time. It never stores the prompt text.
- Find the cause of Ask's 404, fix it, and add a regression test.

**Tests:** the gateway with a fake client (counting, size cap, one retry,
fallback); the Ask regression; the full suite.

**Done when:** every existing AI feature runs through the gateway and behaves
as before, and a manual check (a few credits) shows Ask getting a real model
answer again.

#### 007: Privacy policy names NVIDIA and explains link fetching

**Why:** the draft `/privacy` page still names OpenAI, but notes and link text
now go to NVIDIA. This must be fixed before beta.

**Build:** update `app/templates/privacy.html`, and `terms.html` if needed:
- **NVIDIA is the AI provider.** Say what is sent: your words, source excerpts,
  and voice audio for transcription. If a deployment uses OpenAI instead, the
  policy must say so.
- **Saving a link fetches that page.** For a YouTube link, Life Inbox contacts
  YouTube, so that site sees the link and the server's address.
- Memory and health consent are added in 016, and the full review is 025.

**Tests:** the page names NVIDIA and mentions link fetching, and no longer names
OpenAI as the provider.

#### 008: The five life areas

**Why:** design §4.1 and the research settled on five bots with 3 default
topics each, no catch-all, and Travel as a topic.

**Build:**
- **Bot settings in code** (proposed: `app/bots.py`): keys, names, the 3 default
  topics with their descriptions (research §3), and the "about" text used in
  prompts (research §6.2).
- **Migration:** add `topics.bot_key` and `topics.origin` (built-in, created by
  you, or suggested by a bot).
- **New accounts** get the 15 default topics instead of today's nine.
- **Data migration for existing accounts:**
  - Rename the v1 topics: Learning → Study, Work → Work & career, Money & Admin
    → Bills & subscriptions, Shopping & Errands → Home & errands, Health →
    Medicines & doctors, Travel → Trips & places, Ideas → Skills & projects,
    People → Friends & partner.
  - Add the missing default topics. Every note stays on its topic.
  - Your own topics: a subtopic takes its parent's bot. A main topic gets a bot
    from the keyword rules; if none fits, it gets none and Captain asks you
    (013).
- **"Personal / Reference"** stays as a hidden legacy topic until 014 re-sorts
  its notes, so nothing breaks in between.
- **API:**
  - `GET /api/bots` returns each bot with counts and a status line.
  - `?bot=` works on the list endpoints (items, tasks, calendar events, topics,
    search), for the lens.
  - Creating a topic suggests a bot as well as a parent.
  - `PATCH /api/topics/{id}` can move a topic to another bot. Subtopics always
    share their parent's bot.

**Tests:**
- An empty database gets 5 bots × 3 topics.
- A synthetic v1 database migrates with the right names, all notes kept, and
  your topics placed.
- Topics stay private to each user.
- The `?bot=` filters work.
- The bot suggestion works with mocked AI and offline.

**Done when:** today's screens still work, every topic except the legacy one
has a bot, and the migration passes from empty and from v1.

### Phase 2: The new app (layout A)

#### 009: The three-pane app, with Home, the lens and the note page

**Decide first:** B, C, D.

**Build:**
- **Layout A replaces the long single page** (design §2):
  - **Header:** wordmark, the lens chip ("Viewing: Health ×"), and the account.
  - **Left panel:** Home, Topics and spaces, Timeline, Calendar, Priority,
    Dashboard and Ask me, then up to 5 pinned topics, with the account at the
    bottom.
  - **Centre:** the change 005 composer on top, with the chosen view below.
  - **Right panel:** Captain, then the five bots, each with a one-line status.
    Scout joins in 018.
- **Fits the window.** Only a pane that's genuinely longer scrolls, and there's
  no dead space: Home is a card grid, and cards stretch to fill their row.
  Below 900 px the panes stack, with the composer on top.
- **Home:**
  - the Captain card (greeting and summary; its Needs you cards arrive in 013);
  - This week (spikes and Next up);
  - Today's focus (at most 3, plus "N more waiting");
  - Recently captured (the last 4).
- **The lens:** picking a bot filters every view. Click × or the bot again to
  see everything. With a bot picked, Home becomes that bot's page:
  - its summary (code-written text until 020);
  - its topics and what to do;
  - its week;
  - "What I learned about you" (filled in by 016).
- **One note page**, opened from everywhere:
  - a breadcrumb (bot › topic › subtopic);
  - date and priority chips;
  - Your note and the source;
  - Why it's here (the AI's reason);
  - Related (today's related-items data, moved off the dashboard);
  - actions: Mark done, Move to topic (today's insight endpoint; it counts as a
    correction from 016), and the calendar preview with mock confirm, as today.
- **Nothing from v1 is lost:**
  - account: sign out, sign out everywhere, change password, notification
    settings;
  - the failure and retry center (it moves into Needs you in 013);
  - Ask (it moves to Ask me);
  - tasks: add, complete, reopen, dismiss, snooze, reminder;
  - search, filters, editing note text, and Markdown export (placed per
    decision C);
  - the service worker.
- **The throwaway prototype leaves `app/static`**, so the app never serves it
  (§9).

**Tests:** page structure, lens filtering, note page data, and the "nothing
lost" list, checked by tests where possible.

**Check in the browser:** at 1440×900 and at phone width, every link leads
somewhere and there are no console errors.

#### 010: Topics and spaces, and the topic page

**Build:**
- **Topics grouped by bot**, busiest first, as packed masonry cards. Each card
  shows topics, subtopics (↳) and counts, with empty topics faded. The dashed
  "Add your own topic" card fills the shortest column.
- **"+ New topic"** asks for a name and description, and suggests a bot and a
  parent (from 002 and 008).
- **The topic page** has a breadcrumb, the description, subtopic chips and
  items you can filter by type. Its actions are: edit description, rename, move
  to another bot, and delete (change 003's flow, restyled).

**Tests and check:** grouping and counts, the topic actions, and the packing at
several widths.

#### 011: Timeline, Calendar, Priority and Dashboard

**Decide first:** E, F.

**Build:**
- **Timeline:**
  - a Mon–Sun line with a spike per item (taller means high priority);
  - solid for a confirmed date, dashed for a suggested one;
  - a week/month switch;
  - "Undated: N", which opens Captain.
- **Calendar:**
  - a month grid built on today's calendar events data;
  - dots coloured by bot, solid or dashed;
  - click a day for a pop-up list, then click an item for its note page;
  - drag to reschedule comes later.
- **Priority:**
  - High, Medium and Low columns; drag a card to change it;
  - each card shows its bot, its date (or "No date · set") and Why;
  - opens on Today plus the next 3, with the rest folded into "Backlog (N) ·
    Catch up?" (Scout, 018);
  - optional Group by bot, and + Add task.
- **Dashboard:**
  - captured this week, tasks done, busiest day;
  - where your attention went (per bot);
  - Captain noticed (2–3 patterns, worked out by code);
  - growing and quiet topics;
  - coming up.

**Tests and check:** every view follows the lens, the counts are right, and a
drag saves the priority as your value.

### Phase 3: Captain and filing

#### 012: Dates: the small calendar, exact dates, and where each date came from

**Build:**
- **Migration:** add `tasks.suggested_due_on`. `tasks.due_confidence` takes
  `from_note`, `suggested` or `user_confirmed`, with existing values mapped
  across.
- **`POST /api/tasks/{id}/date` `{due_on, due_time?}`** saves a date as
  "confirmed by you".
- **The picker:**
  - a month grid with the suggestion pre-selected and marked "suggested";
  - an optional "Add a time" (otherwise the item is all-day);
  - Save date and Cancel.
- **It opens from three places:** right after saving ("Coming Saturday → Sat 7
  Nov? Confirm · Change"), from Needs you (013), and from any date chip.
- **Clear dates in your own words** are saved as "from your note". **Fuzzy
  dates** never reach the calendar until you confirm them. There are three chip
  styles: solid, dashed with "confirm", and solid with ✓.
- **A confirmed date flows everywhere:** Calendar, Timeline, Priority (a near
  date raises priority) and reminders.
- **Suggested dates** come from today's date reader for now, and from the
  filing call once 014 lands.

**Tests:** the endpoint, date provenance, time zones (no day shift in India
time), and reminders still firing.

#### 013: Captain's "Needs you" list

**Build:**
- **`GET /api/captain/needs-you` and `POST /api/captain/needs-you/{id}/resolve`**,
  worked out from existing data.
- **Kinds of card:**
  - fuzzy date (opens the picker);
  - missing date on a time-bound task (Set date / Drop it);
  - failed capture (Retry / Add a note / Delete; this replaces the retry
    center);
  - unclear area (rule R6: the top two choices);
  - a topic with no bot (from 008);
  - possible clash (two confirmed items at the same time).
  Topic proposals and facts to confirm join in 020.
- **Cards are ranked**, 3–5 show at a time, they use kind wording, and they
  fill their row.
- **"Not now" and answers are stored**, so a card doesn't come back. Every
  answer is kept as a memory example (016).
- **Home's Captain card and the right-panel badge** both show the list.

**Tests:** each kind appears and resolves; ranking; at most one question per
note (P6); each user sees only their own cards.

#### 014: Filing v2, with one LLM call per note

**Decide first:** G.

**Build:**
- **Filing replaces today's per-item `/api/analyze` call after saving.** Notes
  saved while a call is running go together in the next call, up to 5.
- **Level 0, code (free):** keyword rules in R1–R6 order, similar past notes
  from today's search, and your topic words pick the 1–2 likely bots.
- **Level 1, one call.** It receives:
  - the instructions and rules R1–R6, plus "a date never decides the category";
  - today's date and your time zone;
  - the five bots and their topics: full descriptions for the likely bots,
    names only for the rest;
  - your words, kept separate from the source;
  - the source, cut to 1,500 characters (for links, the link card from 015);
  - up to 3 similar notes, each marked "filed by you" or "filed by AI".

  Memory is added in 017.
- **The call returns:**
  - the bot and topic, how confident it is, and the rule that decided;
  - the two best choices when it's unsure;
  - a title, priority, tags and its reason;
  - tasks, each with the date phrase and a suggested date;
  - for voice, the cleaned transcript;
  - for links, a 2-sentence summary and a suggested action ("Watch later",
    "Try this recipe").
- **Level 2, code checks:** the topic exists and belongs to that bot, every date
  is real, and every task points to this note.
- **Level 3:** one repair call that names the failed check, then the offline
  matcher.
- **Level 4:** if the call is unsure or tied, the note goes to Needs you with
  the two choices. It gets no topic until you pick.
- **Saved in `item_insights`:** the rule, confidence, choices, and who filed it
  (AI, offline, or you). "Why it's here" shows the reason and the rule.
- **Voice takes 2 calls, not 3:** speech-to-text, then this call. The raw
  transcript stays as extracted text; the cleaned one is marked as AI output.
- **The offline matcher is rewritten for the five areas:**
  - rules applied in order, your note checked first;
  - no catch-all, so unclear notes go to Needs you;
  - tasks only from your own words;
  - deadlines like "before the 15th" read by the existing date reader.
- **The catch-all goes.** Notes in "Personal / Reference" are re-sorted into
  existing topics only (change 003's reassignment, at most 25 notes per call).
  Unclear ones go to Needs you, and then the legacy topic is removed.
- **"Analyze Entire Inbox" becomes "Re-sort everything":** at most 25 notes per
  call, only when you ask, and it says how many calls it will make first.
- **A new topic** re-checks only the notes code finds as likely fits (at most
  25, so 0–1 call), then shows "Moved N notes into Python · Undo".
- **Deleting a main topic** keeps today's flow, and anything unclear goes to
  Needs you.
- **No second "double-check" call.**

**Tests (mocked AI):**
- batching;
- the prompt's sections and size;
- the code checks and the repair call;
- the fallback, and Needs you when the call is unsure;
- voice in 2 calls;
- retiring the catch-all, and re-sorting in batches;
- the offline matcher, run on the research doc's 37-note table.

**Live check (manual, a few credits):** run the synthetic notes in §7 against
NVIDIA to confirm the answer format works with the real model. This hasn't been
checked for change 005 either.

**Done when:**
- the synthetic set uses at most 1.2 calls per added note;
- every prompt stays within §6;
- no note is ever filed under a topic that doesn't exist.

#### 015: Smart link capture

**Decide first:** H, I.

**Build**, as proposed when we looked at your YouTube link:
- **Tidy links:** strip tracking parts such as `utm_…` and `si=`. A link you
  saved before reuses its earlier result, with no AI call.
- **Free facts before any AI:**
  - oEmbed for YouTube and similar sites (exact title and channel);
  - structured page data (an article's headline and date, a recipe's
    ingredients and steps, an event's date and place);
  - page tags (title, description, site name);
  - the main text, with menus, footers and cookie banners removed. Check the
    licence of any extraction library first.
- **A link card** of at most 1,500 characters, stored separately from the AI's
  output. It's the "source" the filing call sees.
- **"Limited preview: only the title could be read"** when a page gives almost
  nothing.
- **No YouTube images or players** load in your browser unless decision I
  allows the privacy-enhanced player behind a click.
- **Later and optional:** a YouTube Data API key, and an on-demand "Summarize in
  depth" that sends the full text in pieces. No transcripts for now.
- **The privacy page** adds oEmbed and page-data fetching (extending 007).

**Tests:** saved test pages (a YouTube oEmbed reply, a recipe page, an article,
a blocked page), and duplicates reusing results. Tests never touch the real
internet.

### Phase 4: Memory

#### 016: Memory: what Life Inbox learns about you

**Decide first:** J.

**Build:**
- **Migration:**
  - `memory_facts`: owner, bot, kind (long-term, short-term, or example), text,
    source notes, source kind, status (suggested / confirmed / expired /
    deleted), times seen, valid until, and a core-profile flag;
  - `user_settings`: health-memory consent (catch-up settings come in 018).
- **Where facts come from**, mostly code with no AI call:
  - your corrections (Move to topic, priority changes, date edits) and your
    Needs you picks become examples;
  - dated tasks become short-term facts;
  - the filing call may suggest long-term facts drawn **only from your own
    words**, stored as "suggested".
- **Only trusted memory.** Text from a source never becomes memory unless you
  confirm it.
- **Lifecycle:** suggested → confirmed (seen again, or confirmed by you) →
  expired (plans after their date) or deleted (by you).
- **"What I learned about you"** on each bot page; Captain holds facts that
  span areas:
  - every fact shows its source ("from note #10"), with Confirm, Edit and
    Delete;
  - API: `GET /api/memory`, `PATCH /api/memory/{id}`,
    `DELETE /api/memory/{id}`.
- **Health memory stays off until you allow it.** The consent text says it
  covers family members' medical notes. While it's off, nothing health-related
  is stored or sent as memory.
- **Secrets:** notes that look like passwords (the rules from decision J) are
  hidden in the UI (tap to show), and never go into memory or AI prompts.
- **Export and deletion:** the Markdown export includes memory. Account deletion
  (auth plan, §10) must delete it too.
- **The privacy page** gets a memory section.

**Tests:** the fact sources and lifecycle, per-user privacy, the health gate,
secret hiding and exclusion, and the export.

#### 017: Memory in the filing call

**Build:**
- **Code picks the context for each note (0 calls).** It scores every memory
  by:
  - relevance: shared words with the note;
  - timing: plans close to today rank higher;
  - strength: confirmed beats seen often, which beats suggested;
  - area: whether it belongs to the likely bots.
- **Always included:** upcoming plans for the next 14 days (up to 8) and your
  core profile (up to 5). Then a shortlist of up to 15 more: other facts, your
  corrections, and similar notes.
- **In the prompt**, under "What Life Inbox knows (hints only; your note's own
  words win)". Each line has its label (confirmed by you, seen 3 times, not
  confirmed) and its date.
- **The call says which items it used**, and "Why it's here" names them, for
  example "you usually save coding videos under Skills & projects; your choice
  on 2 Nov".
- **Updates to plans you already have:** "Quiz moved to Thursday" becomes "Move
  Python quiz from Tue 3 Nov to Thu 5 Nov? Yes / No, it's a different quiz",
  not a duplicate task.
- **Size:** the limits in §6, about 3,000 tokens in.
- **The replay test comes before switching it on** (§7):
  - File the synthetic set with and without memory. Switch memory on only if
    more notes are filed correctly and fewer Needs you questions are asked,
    with no more wrong filings.
  - Also check whether code left out context the AI needed. If that happens
    often, switch on the two-call version, where an AI picks the context first,
    perhaps only for notes where code found nothing.

**Tests (mocked AI):**
- selection and limits;
- labels, and the "note wins" instruction;
- health facts and secrets left out;
- the items the call used are saved and shown;
- the update card.

### Phase 5: Helpers

#### 018: Scout, the catch-up helper

**Decide first:** K, L, M, F.

**Also here (deferred by the owner on 2026-11-07):** rethink "Snooze 1 day"
next to Postpone (change 012). The ideas so far: rename it "Remind me
tomorrow", say that the date stays, and hide it on tasks with a set time
(meetings, appointments), where only Postpone makes sense.

**Build:**
- **Migration:**
  - `task_events`: the task, done / rescheduled / dropped, an optional reason,
    by you or by Scout, and when;
  - a Someday flag on tasks;
  - catch-up day and time in `user_settings`.
- **When Scout asks:**
  - the day after a task's date;
  - a weekly catch-up (default per decision L, at most about 10 questions);
  - after a break ("You've been away 9 days, want a 1-minute catch-up?");
  - stale Someday items, monthly.

  Questions appear in the Scout view and the right panel. If you turned on push
  notifications, they also arrive through the existing scheduler in
  `app/notifications/`.
- **Three answers:**
  - Done: the task is completed and leaves Calendar, Priority and Timeline;
  - Not yet, new date: the picker opens;
  - Drop it: the task is dismissed, with an optional reason.

  Code records each answer and updates short-term memory: "Captain updated the
  Learning & work bot's memory: Python quiz: done".
- **Against overwhelm:**
  - Priority opens on Today plus the next 3;
  - bulk actions: "Move everything older than 30 days to Someday", "Snooze
    these to next week";
  - kind wording ("Let's tidy up: 3 quick questions").
- **Timeline ✓ on past days**, if decision F says yes.
- **No AI per question.** The weekly update of long-term facts is in 020.

**Tests:** triggers with a fixed clock, each answer and its effects, the bulk
actions, and notifications going through the existing dispatcher.

#### 019: Ask me v2

**Build:**
- **Routing by code:** the lens if a bot is picked; otherwise the bots of the
  best-matching notes.
- **Evidence:**
  - up to 5 passages from today's search, including your notes on sources;
  - matching memory facts, with the notes they came from;
  - dated tasks for the period you asked about. Code works out what "this week"
    or "Saturday" means.
- **One call.** If nothing matches, there's no call and the answer is "I
  couldn't find that in your notes".
- **Every claim cites its note.** Code checks every citation. If a check fails,
  one repair call; if that fails too, you get today's quoted answer.
- **"How I answered":** which bots were asked, how many memory facts were used,
  and which notes were read.
- **Suggested actions** ("Confirm Saturday's date?") run only when you tap them.
- **`POST /api/ask`** takes the lens.

**Tests (mocked AI):** citations, the lens, date questions, and the honest "not
found" (target 100%).

#### 020: Weekly review, topic proposals and bot summaries

**Decide first:** N.

**Build:**
- **One call per user per week**, run by the existing scheduler, or on your
  first visit after 7 days if the scheduler isn't running. It:
  - merges and trims memory;
  - expires past plans;
  - updates long-term facts from Scout's answers;
  - names topic proposals.
- **Topic proposals:**
  1. Code finds groups: 3 or more notes in one bot that share words and that
     no topic fits.
  2. The weekly call names and describes each group.
  3. Code checks there's no similar topic, that the parent is one of the bot's
     main topics, and that 3 or more real notes support it.
  4. A Needs you card offers Create it / Rename / Not now / Don't suggest this.
     Creating it moves the supporting notes in and records the history
     ("Suggested by the Learning & work bot from notes #12, #14, #15; approved
     by you on …"). "Don't suggest this" is remembered.
- **Migration:** topic history (`topics.created_by`, `evidence_item_ids`,
  `approved_at`) and `topic_proposals` (pending, created, declined, never).
- **"Fact to confirm" cards** come from the weekly call's suggestions, for
  example "You organise college events, right? Yes / No / Edit".
- **Bot summaries** are saved, and rewritten (one call) only when that area has
  changed since the last one.
- **Captain's Home greeting** follows decision N.

**Tests (mocked AI):** one weekly call per user; proposals never create a topic
without you (P1); no duplicates; summaries reused until their area changes.

### Phase 6: Better sources

#### 021: Images: read the text

**Decide first:** O.

**Build:**
- Install and set up OCR (Tesseract) so text in screenshots is read. Add the
  setup steps to `docs/deployment.md`.
- If decision O says yes: one vision call for images with no readable text and
  no note.
- Extracted text stays separate from your note and from the AI's output.

#### 022: PDFs: formulas and scans

**Decide first:** P.

**Build:**
- Better text for formulas, and OCR for scanned pages.
- The filing call still sees only the first part, cut to the §6 limit, unless
  decision P adds a one-time summary.

#### 023: Edit your note on a saved source

**Build:**
- "Edit note" on source cards and on the note page. Change 005 left this out.
- Saving an edit re-files the note (one call).

### Phase 7: Ready for beta

#### 024: "Create New Life" onboarding

**Build:**
- Optional questions after creating an account. Your answers are saved as
  confirmed core-profile facts (016).
- Health-memory consent is asked here, with the family-members wording.
- Filing still works if you skip the questions, since new users start with no
  memory.

#### 025: Privacy and compliance pass, docs, and the push

**Build:**
- **Privacy policy and terms** cover NVIDIA, link fetching, memory, health
  consent, secrets, and export and deletion (GDPR and India's DPDP Act).
- **Decision Q, the AI-processing switch** (auth plan §7). Because every call
  goes through the gateway from 006, it is a single switch.
- **Docs:** `AGENTS.md` (new modules), `docs/architecture.md`,
  `docs/manual-testing.md`, `docs/product-roadmap.md`,
  `docs/milestone-status.md` and `docs/deployment.md`, plus a milestone report
  with exact run commands.
- **Then the review and push in §9.**

---

## 6. AI call limits (part of "done")

**Calls per action:**

| Action | LLM calls | Change |
|---|---|---|
| Add a note, link, PDF or image | **1** (notes saved while a call runs share the next one, up to 5) | 014 |
| Add audio | **2**: speech-to-text, then filing | 014 |
| Answer Needs you, confirm a date, answer Scout, use the lens, move around | **0** | 012, 013, 018 |
| Create a topic | **1–2**: suggest a bot and parent; re-check only the likely notes | 008, 014 |
| Delete a topic | **0** for a subtopic, **1** for a main topic | 003, 014 |
| Re-sort everything (only when you ask) | **1 per 25 notes** | 014 |
| Ask me | **0** if nothing matches, otherwise **1** | 019 |
| Open a bot page | **0** if nothing changed, otherwise **1** | 020 |
| Weekly review, per user | **1** | 020 |
| Captain's greeting | **0**, or **1 a day** (decision N) | 020 |
| Image with no text and no note | **0**, or **1** (decision O) | 021 |
| An answer fails code's checks | **at most 1** repair call | 006 |

A typical day of 10 notes (one of them audio), 3 questions and 1 new topic comes
to about **16 calls**, plus 1 a week. The target is **at most 1.2 calls per
added note** on average.

**Filing prompt limits (014, 017):**

| Part | Limit | About |
|---|---|---|
| Instructions, rules R1–R6, answer format | fixed | 700 tokens |
| Bots and topics | full descriptions for the likely bots, names only for the rest | 500 |
| Your words and the source | your words up to 2,000 characters; source up to 1,500 | 900 |
| Core profile | up to 5 facts | 150 |
| Upcoming plans | up to 8, from the next 14 days | 200 |
| Shortlist | up to 15: other facts, corrections, similar notes | 450 |
| **Total** | **hard cap** | **about 3,000 in, 300 out** |

- A token is about 4 characters. The earlier estimate of about 2,700 assumed a
  smaller shortlist. The agreed version adds the always-included plans and
  profile and a longer shortlist.
- If a prompt would go over the cap, the gateway (006) drops the lowest-scoring
  memory first.
- Ask keeps today's evidence limits (5 passages of up to 400 characters each)
  and adds matching memory facts, within the same cap.

---

## 7. Testing the AI without your real data

AGENTS.md forbids using a real personal database for development or testing, so
the replay set is synthetic:

- **The 37 notes** from the research doc's mapping table, each with its expected
  area, topic and rule. Notes #1–#8 in that table are yours, so the replay set
  uses reworded versions of them.
- **The scenarios from our discussion:** "Quiz moved to Thursday", "Buy cream
  and pasta", "Talk to admin about the budget again", "Call Aditi", a coding
  video with no note, "Buy a gift" with a birthday coming up, "Kal quiz hai",
  and "Doc appt".
- **A synthetic memory** to go with them: core profile, upcoming plans and
  corrections.

Automated tests mock the AI. Runs against the real model are manual and opt-in,
because they cost credits. Each run reports:
- whether the area and topic were right, and which rule decided;
- how many Needs you questions were asked, and how many notes were filed wrongly;
- calls per note and prompt size;
- whether the context the AI needed was in code's shortlist.

---

## 8. How we'll know it works (design §15)

| Measure | Target | Measured by |
|---|---|---|
| Decisions per clear note | 0 | Needs you cards per note (013) |
| Decisions per fuzzy note | at most 1 tap | Needs you cards per note (013) |
| Notes you re-file by hand | falling week over week | corrections in memory (016) |
| Ask answers with a citation, or an honest "not found" | 100% | Ask results (019) |
| Open backlog older than 30 days, after a catch-up | falling | `task_events` (018) |
| AI calls per added note | at most 1.2 on average | the call log (006) |
| Junk or duplicate topics created without you | 0 | topic history (020) |

---

## 9. Review and push

1. **You review** each `docs/changes` document and try each phase.
2. **Decision A:** push 001–005 first, or not.
3. **Final checks:** the full test suite is green, and migrations work from
   empty and from the previous version.
4. **Copy the changes into a git clone** of `deepsleepisgood/life-inbox-copy`,
   on a new branch. This downloaded folder isn't a git repository.
5. **Leave out** `.env` (it holds the NVIDIA key), `.venv/` and `data/`
   (databases, backups, uploads).
6. **If teammates have added migrations** in the meantime, re-chain ours onto
   their newest one and re-run the migration tests.
7. **Branch and tag names** follow AGENTS.md. `docs/milestone-status.md`
   already lists milestones up to 8, so the next is 9.
8. **The prototype** isn't in the app. If it's kept, it goes on a throwaway
   branch with sample notes instead of yours.
9. **Your real notes in docs** (the research doc's §5 notes #1–#8, design
   examples, change docs, the prototype): you decide whether to keep them or
   swap in samples before the team repo sees them.
10. **No secrets in the diff.** Anyone who pulls must run
    `python -m alembic upgrade head`.
11. **Write the milestone report**, with exact run commands, then open the PR.
    No force-push.

---

## 10. Also agreed, outside v2: auth follow-ups

These come from the first part of our work and `docs/production-auth-plan.md`.

**Already done:** password sign-up and login, sessions, logout, change password,
forgot password with a code (shown in the server console), and the 18+
confirmation.

**Not done yet:**
- Real email for codes: **Gmail SMTP first** (it needs no domain), then
  **Resend** once there's a domain.
- SMS codes through **Twilio Verify**.
- Email verification at sign-up, sign-in with a code, and recovery codes.
- Consent records, plus **account export and deletion**, including memory
  (GDPR and DPDP).
- The AI-processing switch (decision Q).
- Per-user upload folders, and making `owner_user_id` required (`NOT NULL`).

**Suggestion:** schedule these after phase 3 or alongside it. Account deletion
and the AI switch must be done before any public beta.

---

## 11. Where each agreed item is built

| What you asked for, or we agreed | Where it came from | Change |
|---|---|---|
| A panel layout: composer in the centre, bots on the right, features on the left; prototype A without blank spaces | You; design §2 | 009 |
| Everything clickable (Health → its notes; a calendar day → the note) | You; P7 | 009–011 |
| Topics and spaces with counts, subtopics and packing that adapts to the space | You; design §3 | 010 |
| Timeline as weekly spikes | You; design §3 | 011 |
| A clickable calendar with a pop-up | You; design §3 | 011 |
| The Priority view | You; design §3 | 011 |
| The Dashboard's contents; "needs review" → Captain; related items → the note page; high priority → Priority | You; design §3 | 009, 011, 013 |
| Captain (the name), Needs you, and summaries that use memory | You; design §5 | 013, 020 |
| A small calendar pop-up with an optional time; confirming "coming Saturday" | You; design §6 | 012 |
| Bots as a lens; no bot shows everything | You; design §7 | 008, 009 |
| Five areas, at most 3 default topics each, unlimited user topics; Travel as a topic; no catch-all | You; research; design §4.1 | 008, 014 |
| Rules R1–R6, with the rule saved and shown | Research §4; design §4.1 | 014 |
| Invent topics with evidence and your approval; their origin remembered | You; design §4.3 | 008, 020 |
| See what happened after each add, the AI's reason, and where it filed the note | You | 009, 014, 017 |
| A catch-up helper: tick or cross, updating the bots' memory and time memory | You; design §9a | 018 |
| Long-term and short-term memory | You; design §8 | 016 |
| Memory in the filing prompt with a limit; code picks the context; the replay test; the two-call option | You; our discussion | 017 |
| "Quiz moved to Thursday" updates the existing task | Our discussion | 017 |
| A smarter Ask me that uses memory and the bots | You; design §9b | 019 |
| One LLM call per note; limits per action; no whole-inbox calls; voice in 2 calls | Our discussion | 006, 014, §6 |
| One weekly call; saved bot summaries | Our discussion; design §10 | 020 |
| Efficient, high-quality link capture (oEmbed, link card, one call, deep dive on demand) | You; our YouTube discussion | 015 |
| YouTube fetching and privacy; the policy names NVIDIA | You; design §11 | 007, 015, 025 |
| Health consent that covers family members; passwords hidden and never sent | Research §6.3; design §8.5, §11 | 016, 024 |
| Export and deletion include memory | Design §8.5 | 016, §10 |
| Learning about you from day one ("Create New Life" questions) | You; design §8.2 | 024 |
| Editing your note on a source | Change 005's next steps | 023 |
| OCR, PDF formulas and scans | Change 005; the design's fixes list | 021, 022 |
| Ask's NVIDIA 404 | The design's fixes list | 006 |
| Offline mode's noisy tasks | Change 005's known limits | 014 |
| A live-model check of the answer format | Change 005's known limits | 014 |
| Each change documented (problem, solution); push only after your review | You | §1, §9 |
| The theme choice | Design §16 | Decision B |
| Auth follow-ups (Gmail SMTP, Resend later, Twilio, GDPR and DPDP) | Phase 1 decisions; auth plan | §10 |
| The same stack (no React or Vue, no vector database) | AGENTS.md | §1 |

**Known limits we're keeping:** one attachment per save; the calendar adapter
stays preview plus mock confirm; drag-to-reschedule in the calendar comes later.
