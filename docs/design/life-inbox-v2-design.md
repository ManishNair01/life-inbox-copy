# Life Inbox v2: design

**Status:** Draft for team review. Nothing in this document is built yet.
**Date:** 2026-11-02
**Prototype:** `docs/design/prototype/new-ui-prototype.html` (variant **A** was chosen).
Open the file in a browser. Since change 009 it is no longer served by the app.
**Related:** `docs/changes/001`–`005` (already built, not yet pushed),
`docs/research-memorae.md` (competitor research),
`docs/research-life-categories.md` (why these five life areas, §4.1), and
`docs/design/life-inbox-v2-build-plan.md` (how and in what order it gets
built).

---

## 1. Why v2

### The goal

> *A person writes everything down here and there. Life Inbox should organise
> it so well that they don't have to think much.*

v2 turns a general-purpose AI into a **precise, personal organiser**. It does
that by giving the AI a structure (a crew of bots), a memory of the user, and
strict rules that stop it guessing.

### Problems with v1

1. **One long page.** Everything is stacked vertically, so users scroll to find
   anything.
2. **Nothing links to anything.** You can see a note is in "Health", but you
   can't click Health.
3. **Generic AI answers.** The AI knows nothing about the user. It also once
   created junk topics such as "Ideas: Product, business…" (fixed in change 004).
4. **The backlog grows forever.** Old tasks pile up and the user feels
   overwhelmed.
5. **Fuzzy dates are lost.** "Coming Saturday" never becomes a real date, so it
   never reaches the calendar.

### Design principles

| # | Principle | In practice |
|---|---|---|
| P1 | **File by choosing, invent by proposing** | When filing a note, the AI may only pick an existing topic. New topics are proposed with evidence and created only after the user approves. |
| P2 | **Every fact has a source** | Dates, tasks and memory facts link back to the note they came from. |
| P3 | **Ask when unsure, never guess** | Unclear dates or topics go to Captain's "Needs you" list. |
| P4 | **Keep the user's words separate from the AI's** | User notes, source text, AI suggestions and user confirmations are stored and shown separately. This is an AGENTS.md rule. |
| P5 | **Code checks the AI** | Dates must be real dates, topics must exist, tasks must come from real notes. |
| P6 | **At most one question per note** | Clear notes need **0** decisions; fuzzy ones need **1** tap. |
| P7 | **Everything visible is clickable** | Every item opens the same note page; every topic, date and bot is a link. |
| P8 | **The user owns their memory** | Every learned fact is visible, editable and deletable. Health memory needs explicit consent. |

---

## 2. Layout A: three panes

```
┌──────────────────────────────────────────────────────────────────────────┐
│ [logo] Life Inbox     Viewing: Health ×                            (A)   │  header
├──────────────┬───────────────────────────────────────────┬───────────────┤
│ Home         │ ┌ composer (always on top) ─────────────┐ │ YOUR CREW     │
│ Topics…      │ │ note… [+Link][+PDF][+Image][+Audio] Add │ │ Captain (3)   │
│ Timeline     │ └───────────────────────────────────────┘ │ Scout   (2)   │
│ Calendar     │  HOME (card grid) or the selected view    │ LIFE BOTS     │
│ Priority     │  ┌ Captain: greeting + Needs you ──────┐  │ Learning …    │
│ Dashboard    │  └─────────────────────────────────────┘  │ quiz Tue 11:00│
│ Ask me       │  ┌This week┐ ┌Today's focus┐ ┌Recent───┐ │ Money …       │
│ PINNED       │  └─────────┘ └─────────────┘ └─────────┘ │ Health …      │
│ Study 2 …    │                                           │ People …      │
│ (account)    │                                           │ Fun …         │
└──────────────┴───────────────────────────────────────────┴───────────────┘
   features            everything you're doing                 which part of life
```

### Rules

- **The app fits the window.** The page itself never scrolls; only a pane whose
  content is genuinely longer scrolls inside itself.
- **No dead space.** Home is a card grid that reflows to fit, and Topics uses
  measured masonry packing. Side panels fill their full height: pinned topics
  and the account sit at the bottom of the left panel, and bot status lines
  fill the right.
- **The composer sits at the top of Home only.** It's the single capture box
  from change 005: note, plus an optional attachment. Every other view keeps
  its space for its own job, and the same composer opens there as a panel from
  "+ New note" in the header, the N key, or a "+" button on phones (change
  011a, the owner's call: the composer on top "takes the main functionality"
  of Timeline, Calendar, Priority, Dashboard, Ask me, and confused Topics and
  spaces).
- **Left panel = how to look:** Home, Topics and spaces, Timeline, Calendar,
  Priority, Dashboard, Ask me, plus up to 5 **pinned topics** (the busiest, with
  counts).
- **Right panel = which part of life.**
  - **Crew:** Captain and Scout, with "needs you" counts.
  - **Life bots:** each bot has a one-line status, for example
    *"Take Python quiz · Tue 3 11:00"*, *"Nothing yet"*.

### Home after login (no bot selected)

| Card | Shows |
|---|---|
| **Captain** (full width) | Greeting, a 1–2 line summary, and up to 3 "Needs you" cards side by side |
| **This week** | Spike chart for Mon–Sun, plus **Next up** (the next 3 dated items) |
| **Today's focus** | At most **3** items, plus "N more waiting" |
| **Recently captured** | The last 4 items, with type tags and topic links |

### Linking rules

- **One note page.** Every item, wherever it appears, opens the same note page:
  - a breadcrumb (*bot › topic › subtopic*);
  - date and priority chips;
  - "Your note", the source, and "Why it's here" (the AI's reason);
  - **Related** notes;
  - actions: Mark done, Move to topic.
- **Topic chips** open the topic page, **date chips** open the date picker, and
  **calendar days** open a day pop-up.
- **Breadcrumbs and Back** always return you to where you came from.

### Phones

Below 900 px the panes stack: left and right become drawers or tabs, and the
composer stays on top.

---

## 3. The left panel, feature by feature

| Feature | What it is | Key behaviour |
|---|---|---|
| **Topics and spaces** | All topics grouped **by bot**, as masonry cards | Busiest bots first. Each card lists topics, subtopics (↳) and counts; empty topics are faded. Every bot starts with its 3 default topics (§4.1), and users can add as many as they like. "+ New topic" opens the name + description form, with the subtopic suggestion (change 002). Clicking a topic opens its page. |
| **Topic page** | One topic | Breadcrumb, description, subtopic chips, items filterable by type. Actions: edit description, rename, move to another bot, delete (change 003). |
| **Timeline** | *"How heavy is my week?"* | Mon–Sun line with spikes per item (taller = high priority). Solid = confirmed date, dashed = suggested. Week/month switch, "Undated: N" leading to Captain. **Later:** past days show completed ✓. |
| **Calendar** | *"What exactly is on the 7th?"* | Month grid; dots coloured by bot, solid or dashed. Click a day for a pop-up list; click an item for the note page. **Later:** drag to reschedule. |
| **Priority** | What to do, by urgency | High, Medium and Low columns; drag to change. Each card shows its bot, date (or **No date · set**) and **Why**. Defaults to **Today and the next 3**; the rest folds into "Backlog (N) · Catch up?" Optional "Group by bot". |
| **Dashboard** | Your life at a glance (reflection, not a to-do list) | Captured this week, tasks done, busiest day; **where your attention went** (per bot); **Captain noticed** (2–3 patterns); growing and quiet topics; coming up. The "Related items" list is removed from here and shown inside each note instead. |
| **Ask me** | Questions about your inbox | See §9. |

**Everything here follows the lens (§7).**

---

## 4. The bots

### 4.1 Life areas: five bots, three default topics each

The five areas come from `docs/research-life-categories.md`, which compares
wellbeing frameworks (WHOQOL, OECD), organising methods (PARA, GTD), time-use
surveys and studies of what people actually save in notes and reminders.

| Bot | Default topics (3) | Covers | Specialist extraction |
|---|---|---|---|
| **Learning & work** | Study · Work & career · Skills & projects | What you study, earn a living from, or build skills for, including college events you help run | Exams, deadlines, study tasks, meetings, interviews |
| **Money & home** | Bills & subscriptions · Bank, tax & documents · Home & errands | Running your household and your own money | Amounts, due dates, renewals, subscriptions, documents |
| **Health** | Medicines & doctors · Fitness & food · Mind & mood | Your body and mind, plus the medical needs of people you care for | Medicines, doses, appointments, refills *(needs consent, §8)* |
| **People** | Family · Friends & partner · Occasions & gifts | Your relationships and the occasions you share | People, birthdays, dates, gifts, follow-ups |
| **Fun & interests** | Watch, read & listen · Hobbies (with the subtopic Cooking) · Trips & places | What you do for enjoyment and curiosity, including holidays | Watch lists, recipes, trip dates, bookings, packing |

- **Three defaults, no ceiling.** Each bot starts with exactly 3 topics. Users
  can add as many topics and subtopics as they like, for example *Study ›
  Python* or *Medicines & doctors › Pill reminder*.
- **No catch-all.** There is no "Personal / Reference" topic, because about
  half of all notes are kept for reference, so it would swallow the inbox.
  Reference notes are filed by subject (a wifi password goes to Home & errands,
  a passport to Bank, tax & documents). A note that fits nowhere waits in
  Captain's "Needs you" list, which is a state, not a topic.
- **Travel is a topic, not a bot.** Holidays go to Fun & interests › Trips &
  places, and work trips go to Work & career.
- **Every note gets exactly one bot and one topic.** When a note could fit two,
  these rules decide. Apply them in order and stop at the first that fits:

| # | Rule | Example |
|---|---|---|
| R1 | Anything **medical** goes to **Health**, including family members' | "Pick up Dad's prescription" → Medicines & doctors |
| R2 | **Your own** bills, subscriptions, fees and paperwork go to **Money & home**. One-off purchases for a plan (a gift, a trip booking) don't count | "Cancel Netflix on 15 Dec" → Bills & subscriptions |
| R3 | **The purpose in your note beats the content** | Pasta recipe "for my date" → People › Occasions & gifts |
| R4 | **A college's or employer's** money and tasks go to **Learning & work** | Halloween event budget → Study |
| R5 | Otherwise **the subject decides, not the format**; a video or PDF is only a container | Hypothesis Testing PDF → Study |
| R6 | Still unclear → **don't guess.** Ask in "Needs you" with the top two choices; the user's pick becomes a memory example | Nemotron video with no note → Skills & projects or Watch, read & listen? |

Captain's filing prompt includes R1–R6 word for word, and the rule that fired
is saved with the filing reason ("Why it's here"), so every placement can be
explained and corrected.

Bots are **a level above topics**: *bot → topic → subtopic*, with subtopics one
level deep (change 002). **Every topic belongs to exactly one bot.** When a topic
is created, Life Inbox suggests its bot, and the user can change it.

**Moving from v1.** A data migration renames the v1 built-in topics (Learning →
Study, Work → Work & career, Money & Admin → Bills & subscriptions, Shopping &
Errands → Home & errands, Health → Medicines & doctors, Travel → Trips &
places, Ideas → Skills & projects, People → Friends & partner) and adds the
missing defaults. Notes in "Personal / Reference" are re-sorted into existing
topics only, using the reassignment from change 003, and unclear ones go to
"Needs you". User-created topics keep their names and are given a bot.

### 4.2 How a note is filed (the grounding ladder)

```
note + your context
   │
1. Captain: which bot?                 → choose 1 of the 5 bots, using rules
   │                                     R1–R6 (§4.1); unsure → "Needs you"
2. Bot: which topic in MY area?        → choose 1 of its topics
   │                                     (3 defaults + the user's own)
3. Bot: details                        → dates, people, amounts, tasks:
   │                                     ONLY what's written; unclear → "Needs you"
4. Code checks                         → topic exists, date is a real date,
   │                                     task points to this note
5. Save                                → topic, priority, tags, reason (with the
                                         rule that fired), tasks, memory updates
                                         (as suggestions)
```

- **Why the ladder helps:** each step is a small, checkable choice from a short
  list. This is what stops made-up answers (P1, P5).
- **Cost:** steps 1–3 run as **one AI call**. Before it, code (no AI) picks the
  1–2 likely bots and the context for the call (§8.4), so there is no separate
  routing call. If the answer fails code's checks, one repair call is made; if
  the AI is still unsure, the note goes to "Needs you" (§10).

### 4.3 How a new topic gets invented (P1)

1. **A bot notices a pattern.** For example, 3 or more notes in its area share
   a theme ("Statistics") and none of its topics fits them well.
2. **Code checks the proposal before it is shown:**
   - no similar topic exists ("Stats", "statistics");
   - the proposed parent is one of the bot's main topics;
   - at least 3 real notes back it up.
3. **It appears in Captain's "Needs you" list:** name, description, the evidence
   notes, and the buttons **Create it / Rename / Not now / Don't suggest this**.
4. **If the user creates it:** the topic is created, the evidence notes move in,
   and its history is recorded: *"Suggested by the Learning & work bot from
   notes #12, #14, #15; approved by you on …"*.
5. **"Don't suggest this"** is remembered as a preference.

**Every topic carries its origin** (built-in, created by you, or suggested by a
bot and approved). Captain uses this when organising and summarising.

---

## 5. Captain

The name *Captain* matches the user's idea of a team of soldiers.

### Responsibilities

1. **Routes** notes and questions to the right bot(s). Routing is done by code
   before the AI call (§4.2), not by an extra call.
2. **Runs the "Needs you" list**, one place for every question, each with a
   one-tap answer:

   | Kind | Example | Answer |
   |---|---|---|
   | Fuzzy date | "Make white sauce pasta: you wrote 'coming saturdy'" | Date picker (§6) |
   | Missing date on a time-bound task | "Talk to Admin about Halloween budget has no date" | Set date / Drop it |
   | Unclear area (rule R6) | "Nemotron video, saved without a note: Skills & projects or Watch, read & listen?" | Pick one (kept as a memory example) |
   | Topic proposal | "Create Statistics under Study?" | Create / Rename / Not now / Never |
   | Possible clash | "Saturday: date night vs Halloween event?" | Check / Ignore |
   | Fact to confirm | "You organise college events, right?" | Yes / No / Edit |
   | Failed capture | "This link couldn't be read" | Retry / Add a note / Delete |

   It shows **3–5 items at a time, ranked**, so it never nags.
3. **Approves memory updates** from the bots and Scout (§8): rules first, AI
   only when needed.
4. **Writes the daily briefing:** the Home summary and "Today's focus" (at most
   3).
5. **Never takes outside actions** (calendar writes, messages) without the
   user's explicit confirmation. This is an AGENTS.md rule.

---

## 6. Dates: Captain asks, a small calendar answers

### When the date picker appears

- **Right after saving** a note with a fuzzy date, as a card in the middle of
  a dimmed page: *"Is this the right day?"* with the day shown as a calendar
  page, **Yes, Sat 7 Nov**, **Pick another day** and **Ask me later**. (Planned
  as a gentle line that doesn't interrupt; the owner found that too easy to
  miss, change 012.) A date left for later stays in Captain's card on Home.
- **In Captain's "Needs you" list.**
- **On any date chip**: task, note page, calendar or priority card.

### What the picker shows

- The month grid, with the **AI's suggestion pre-selected** and outlined as
  "suggested".
- An optional **"Add a time"**; without it the item is all-day.
- **Save date** and **Cancel**.

### Clear dates versus fuzzy dates

- **Clear dates in the user's own words** ("15th December 2026") are saved
  automatically as *"from your note"*.
- **Fuzzy dates** ("coming Saturday", "next week", typos such as "saturdy") are
  **never** placed on the calendar without the user's confirmation.

### Three kinds of date

| Kind | Shown as | Example |
|---|---|---|
| From your note | Solid chip | "Tue 15 Dec" |
| Suggested by the AI | Dashed chip, "confirm" | "Sat 7 Nov? confirm" |
| Confirmed by you | Solid chip with ✓ | "Sat 7 Nov · 19:30 ✓" |

**Once confirmed, the date flows everywhere:** Calendar, Timeline, Priority (a
near date raises priority) and reminders.

### What already exists

- Tasks already store `due_on`, `due_time`, `due_confidence`, `snoozed_until`
  and `reminder_at`.
- `POST /api/tasks/{id}/timing` confirms a timing **phrase**.

**What's new:** an endpoint to set an **exact date and time** chosen by the
user, marked as "confirmed by you". The AI should also return a **suggested ISO
date** alongside the phrase it kept from the note.

---

## 7. The lens: bots × features

| Selected on the right | Left-panel features show | Header |
|---|---|---|
| **Nothing** (after login) | **Everything** from all notes | "Showing everything" |
| **Captain** | Everything, plus Captain's "Needs you" on Home | "Showing everything" |
| **A bot** (e.g. Health) | **Only that bot's** items in every feature (Calendar, Priority, Topics, Ask me…) | **"Viewing: Health ×"** |
| Two bots *(later)* | Both | "Viewing: Health + Money ×" |

- **Clicking a bot** on Home opens that **bot's page**:
  - its summary;
  - its categories;
  - what you need to do;
  - its timeline;
  - "What I learned about you" (editable).
- **Clicking the × or the bot again** returns to everything.

---

## 8. Memory

Memory lets the AI give **personal, specific** answers without ever retraining
the model.

### 8.1 Two kinds of memory

| | **Persona memory** (who you are) | **Time memory** (what's happening now) |
|---|---|---|
| Holds | Lasting facts and habits | Plans, their dates and outcomes |
| Example | "Student, learning Python and Statistics"; "Cooks the recipes planned for dates" | "Date night 7 Nov: happened, pasta cooked"; "Halloween budget: no longer needed" |
| Changes | Slowly, as patterns repeat | Every week, mostly through Scout (§9a) |
| Belongs to | A bot (or Captain, for cross-area facts) | The bot that owns the item |

### 8.2 Where facts come from (strongest first)

1. **The user's corrections:** "Move to topic", priority changes, date edits.
2. **The user's decisions:** accepted or declined suggestions, Scout answers.
3. **The user's topics, descriptions, and the notes they attach to sources.**
4. **Task outcomes:** done, dropped or ignored.
5. **Patterns the AI notices.** These start as **suggestions** and are shown
   under "What I learned about you".
6. **Optional "Create New Life" questions** on day one.

### 8.3 Fact lifecycle

`suggested → confirmed` (seen again, or confirmed by the user) `→ expired`
(time facts pass their date) or `→ deleted` (by the user).

### 8.4 How facts are used in an AI call (the context pack)

Memory goes into the same single filing call. There is no extra call to choose
it.

1. **Code picks the context, for free.** Every memory is scored by relevance
   (shared words with the note), timing (plans close to today), strength
   (confirmed > seen often > suggested) and area (the 1–2 likely bots).
2. **Always included:** upcoming plans for the next 14 days (up to 8) and the
   core profile (up to 5).
3. **Then a shortlist of up to 15 more:** other facts, the user's corrections
   as examples, and similar past notes with where they ended up.
4. **In the prompt** under *"What Life Inbox knows (hints only; your note's own
   words win)"*. Each line carries its label (confirmed by you, seen 3 times,
   not confirmed) and its date.
5. **The AI uses only what matters and says which items it used.** "Why it's
   here" shows them, so a decision based on memory can be checked and
   corrected.
6. **Hard limit:** about 3,000 tokens in. Each part has its own cap (build plan
   §6); if the prompt is too long, the lowest-scoring items are dropped.

**Safety rules:**
- **The note wins.** What the user writes now beats what Life Inbox remembers.
- **Only trusted memory.** Facts come from the user's own words and actions. A
  source's own text never becomes memory unless the user confirms it.
- **Fresh facts only.** Facts carry their status and date, and finished or
  dropped plans drop out.
- **Protected data.** Health facts go in only with consent, and passwords are
  never sent.

**Proven before it's switched on.** A replay test on synthetic notes compares
filing with and without memory. If code often leaves out context the AI
needed, a two-call version (an AI picks the context first) can be switched on,
perhaps only for notes where code found nothing.

Captain compacts the memory weekly, merging and trimming facts so that calls
stay small and cheap.

### 8.5 Rules

- **Per user and private,** stored like topics (`owner_user_id`).
- **Every fact shows its source** ("from note #10") and can be edited or deleted.
- **Health memory is off until the user allows it.** Health data is a special
  category under GDPR Art. 9 and is handled strictly under India's DPDP Act.
  The consent text must say it also covers family members' medical notes,
  because rule R1 files those under Health.
- **Export and deletion** (planned in `docs/production-auth-plan.md`) include
  memory.

---

## 9. The helpers

### 9a. Scout (catch-up)

**Goal:** stop the backlog overwhelming the user, and keep time memory true.

**When Scout asks:**

1. **The day after a task's date passes:** *"Did you take the Python quiz
   yesterday?"*
2. **A weekly catch-up:** default Sunday evening, configurable; at most about
   10 questions, about a minute.
3. **After a break:** *"You've been away 9 days, want a 1-minute catch-up?"*
4. **Stale "someday" items:** checked monthly.

**The three answers:**

| Answer | Effect in the app | Report to Captain → memory |
|---|---|---|
| **Done** | Marked complete; leaves Calendar, Priority and Timeline (later shown as ✓ in history) | Time memory: "X done"; persona patterns strengthened |
| **Not yet, new date** | Date picker opens | Time memory: "X rescheduled" |
| **Drop it** (optional reason) | Dismissed and removed from lists | Time memory: "X no longer needed" |

**Protecting the user from overwhelm:**

- **Priority opens on Today plus the next 3;** the rest is folded away.
- **Bulk options:** "Move everything older than 30 days to Someday", "Snooze
  these to next week".
- **Kind wording:** *"Let's tidy up: 3 quick questions"*, not "12 overdue!".

**Cost:** mostly **no AI**, because questions come from tasks and dates and the
user's taps are the answers. One combined AI call per week updates persona
facts from the outcomes.

### 9b. Ask me

The user asks a question in their own words. The pipeline:

1. **Captain routes it**, by code, to the relevant bot(s). With a lens
   selected, it only looks in that bot's area; otherwise it uses the bots of
   the best-matching notes.
2. **Evidence is gathered:**
   - the bot's memory facts (persona and time);
   - matching notes, from the existing keyword and TF-IDF search, plus the
     user's notes on sources (change 005);
   - dates and tasks. Code works out what "this week" or "Saturday" means, so
     the AI never does date maths.
3. **The AI answers only from that evidence.** Every claim links to its note
   (`#2`). With no evidence, it says *"I couldn't find that in your notes"*.
4. **"How I answered"** is shown: the bot asked, the number of memory facts
   used, and the notes read.
5. **It may suggest actions,** for example *"Confirm Saturday's date?"*, but
   **never** carries them out without the user's tap.
6. **Cost:** no call if nothing matches; otherwise one AI call with only the
   relevant evidence, never the whole inbox. If a citation fails code's check,
   one repair call is made, then the plain quoted answer.

**Examples from the prototype:**

| Question | Answer |
|---|---|
| "Which video is for Python?" | *"None of your saved videos is marked as for Python. The closest is the Nemotron video [#7], but you didn't say so, so I won't assume it."* (honest: no evidence, no claim) |
| "What am I cooking for my date?" | *"White sauce pasta [#2]… the date isn't confirmed yet."* plus a **Confirm Saturday's date** button |
| With the Money lens: "What do I have this week?" | *"Nothing dated this week in Money & home. Next up: Cancel Netflix on 15 Dec [#5]."* |

---

## 10. AI cost and reliability

| Action | AI calls | Notes |
|---|---|---|
| Add a note, link, PDF or image | **1** | Notes saved while a call runs share the next one (up to 5) |
| Add audio | **2** | Speech-to-text, then filing; the transcript clean-up is part of filing |
| Answer "Needs you", confirm a date, Scout answers, lens, navigation | **0** | Plain code |
| Create a topic | **1–2** | Suggest its bot and parent; re-check only the notes code finds as likely fits |
| Delete a topic | **0** or **1** | 0 for a subtopic; 1 for a main topic |
| Re-sort everything | **1 per 25 notes** | Only when the user asks |
| Ask me | **0** or **1** | 0 if nothing matches |
| Bot summary | **0** or **1** | Saved; rewritten only when that area changes |
| Weekly review (memory, Scout outcomes, topic proposals) | **1 per week** | One batched call per user |
| An answer fails code's checks | **+1 at most** | One repair call |

A typical day (10 notes, one of them audio; 3 questions; 1 new topic) is about
16 calls, plus 1 a week.

- **How a call is made:** code first (likely bots, context, dates), then one AI
  call, then code checks. One repair call happens only if a check fails. If the
  AI is still unsure, the note goes to "Needs you". There's no "double-check"
  call by a bigger model; asking the user once is cheaper and teaches the
  memory.
- **No whole-inbox calls.** Sources are cut to 1,500 characters, and each
  filing prompt has a hard limit of about 3,000 tokens (§8.4).
- **One path for every call**, so calls are counted (target: at most 1.2 per
  added note) and limits are enforced in one place.
- **Fallbacks:** without an AI key, or on an AI error, the offline matcher is
  used (keywords, the user's topic words, context first; changes 002 and 005).
- **Validation:** every AI result is checked by code before saving (P5).
  Invalid parts are dropped or sent to "Needs you".

---

## 11. Privacy and compliance

- **Disclosure:** the privacy policy must name **NVIDIA** as the AI provider
  (it still says OpenAI) and explain link fetching (see the Memorae and YouTube
  discussion). **Must be done before beta.**
- **Health memory:** opt-in, switchable off, and deletable.
- **Memory transparency:** "What I learned about you" lists every fact with its
  source.
- **Secrets in notes:** notes such as a wifi password (filed under Home &
  errands) should be masked in the UI and left out of AI prompts. Still to be
  designed.
- **User control:** outside actions always need confirmation. Captain
  suggests; the user decides.
- **Export and deletion** cover notes, topics, memory and history.

---

## 12. Proposed data model changes

| Change | Purpose |
|---|---|
| `life_bots` (or a static config to start), and `topics.bot_key` | Which bot owns each topic |
| A data migration from the v1 built-in topics to the five bots and their default topics (§4.1) | Existing users keep every note, filed under the new areas |
| `topics.origin`, `topics.created_by`, `topics.evidence_item_ids`, `topics.approved_at` | Topic history (§4.3) |
| `topic_proposals` (status: pending, created, declined, never) | Proposals and "don't suggest" memory |
| `memory_facts` (owner, bot, kind: persona or time, text, source_item_ids, source_kind, confidence, status, valid_until, created/updated) | Memory (§8) |
| `task_events` (task, kind: done, rescheduled, dropped; reason; by: user or scout; at) | Outcomes for Scout and time memory |
| `tasks.due_confidence` values `from_note`, `suggested`, `user_confirmed`, plus `tasks.suggested_due_on` | Date provenance (§6) |
| `user_settings` (catch-up day and time, health-memory consent, lens defaults) | Preferences and consent |
| An AI call log (owner, action, model, outcome, prompt size; never the prompt text) | Counting calls and size (§10) |
| `item_insights` filing columns: the rule that decided, confidence, the two choices when unsure, who filed it | "Why it's here" and R6 |
| `memory_facts` kind `example` (corrections and "Needs you" picks), and a core-profile flag | Context pack (§8.4) |
| A Someday flag on tasks | Scout's bulk "Move to Someday" (§9a) |

All of these go through Alembic migrations, as AGENTS.md requires.

---

## 13. Proposed API

| Endpoint | Purpose |
|---|---|
| `GET /api/bots` | Bots, with status line and counts |
| `GET /api/bots/{key}` | Bot page: summary, topics, tasks, timeline, memory |
| `GET /api/captain/needs-you` · `POST /api/captain/needs-you/{id}/resolve` | The "Needs you" list |
| `POST /api/tasks/{id}/date` `{due_on, due_time?}` | Set an exact date ("confirmed by you") |
| `GET /api/scout/questions` · `POST /api/scout/answers` | Catch-up |
| `GET /api/memory` · `PATCH/DELETE /api/memory/{id}` | View and edit memory |
| `PATCH /api/items/{id}/insight` (exists) + a UI button | **Move to topic**, which becomes a memory signal |
| `POST /api/ask` (exists) | Upgraded per §9b; `lens` parameter, citations, "how I answered" |

Every endpoint that lists items accepts `?bot=` for the lens.

---

## 14. Build plan

The full plan is `docs/design/life-inbox-v2-build-plan.md`. It has changes
006–025 in build order, the decisions each one needs first, the AI-call and
prompt limits, the replay test, and the review-and-push checklist. It also
covers the fixes listed here before (Ask's NVIDIA 404, smart link capture, OCR,
PDF formulas and scans).

---

## 15. How we'll know it works

| Measure | Target |
|---|---|
| Decisions per clear note | **0** |
| Decisions per fuzzy note | **1 tap** at most |
| Notes the user re-files by hand | Falling week over week (memory is learning) |
| Ask me answers with at least one citation, or an honest "not found" | **100%** |
| Open backlog older than 30 days after a catch-up | Falling |
| AI calls per added note | **≤ 1.2** on average |
| Junk or duplicate topics created silently | **0** (P1) |

---

## 16. Decisions

### Decided

- **Layout A** (three panes, fits the window, card-grid home, masonry topics).
- **Captain** is the main bot's name.
- **Bots act as a lens;** with nothing selected, every feature shows everything.
- **Fuzzy dates** are asked about right after saving **and** in "Needs you".
- **Clear dates in the user's own words** are saved automatically.
- **File by choosing, invent by proposing,** with approval.
- **Scout** is a separate helper that reports to Captain.
- **Five life bots,** each starting with 3 default topics that users can add
  to without limit: Learning & work, Money & home, Health, People, Fun &
  interests (§4.1). No catch-all; Travel is a topic (Trips & places). Based on
  `docs/research-life-categories.md`.
- **The calm palette** for this design: powder blue, lavender, soft red, serif
  headings.
- **One AI call per note.** Code picks the context (memory, within a hard
  limit), the AI uses it and says what it used, and code checks the result
  (§8.4, §10). There are no "double-check" calls; when unsure, ask the user.

### Open

1. **Visual style:** the current team build uses the dark "neo-brutalist"
   theme, while this design uses the calm palette. **The team needs to choose one.**
2. **Scout's name:** Scout, Recap or Check-in?
3. **Weekly catch-up default:** Sunday evening?
4. **Dropped tasks:** should Scout ask why (optional reasons)?
5. **Timeline history:** show completed ✓ on past days?
6. **Priority scheme:** High/Medium/Low, or urgent/important quadrants?
7. **Multi-bot lens:** now or later?
8. **Captain's Home greeting:** a code template, or written by the AI once a
   day?
9. **Images with no readable text and no note:** an extra AI call to describe
   them, or none?
10. **Search, the full notes list and Markdown export:** where do they live in
    layout A?

The build plan (§3) lists every open decision with the change it must come
before.
