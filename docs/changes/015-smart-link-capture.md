# 015: Smart link capture

**Date:** 2026-11-08 · **Status:** Done, not pushed · **Build plan:** phase 3,
change 015 · **Decisions:**
- **H:** oEmbed and free page data only, no YouTube API key;
- **I:** text only, with no YouTube pictures or players.

## Problem

- **A link's "source" was the page's raw text,** cut short. For many sites,
  YouTube especially, that's a vague title and a lot of menu and footer text.
  It's a poor thing to file a note by.
- **Shared links carry tracking parts** (`utm_source=…`, `si=…`). The same link
  saved twice was read, and filed with AI, twice.
- **When a page gave almost nothing,** nothing said so.

## Solution

### Tidy links

- **Before anything is saved, tracking parts are removed:** `utm_*`, `si`,
  `fbclid`, `gclid`, `igshid`, `feature` and the like. YouTube's short forms
  (`youtu.be/…`, `m.youtube.com`) become one canonical link.
- **What's stored is the tidy link,** for example
  `https://www.youtube.com/watch?v=abc123&t=42`. Parts that matter, like the
  time `t`, stay.

### Free facts before any AI

- **YouTube and Vimeo:** their public oEmbed service gives the video's exact
  title and channel ("Building agents with Nemotron", by "NVIDIA Developer").
  The note's title uses it.
- **The page's own structured data** (schema.org, which sites publish for
  search engines):
  - a recipe's ingredients, steps, time ("1 h 30 min") and servings;
  - an article's headline, date and author;
  - an event's date and place;
  - a video's date and length.
- **Page tags:** title, description and site name.
- **The main text,** with menus, headers, footers, cookie and consent banners,
  sidebars, "related" boxes and comment areas left out.
- **No extraction library:** only Python's standard library reads pages, so
  there's no third-party licence to check (the plan asked).

### The link card

- **Stored on the note** (`inbox_items.link_card`) and **written by code, not
  AI,** apart from the AI's output.
- **What's in it:** the kind (video, recipe, article, event, page), the title,
  the site or channel, the facts, the description, and up to 1,500 characters
  of text.
- **It's the "source" the filing call sees for a link (014),** kept apart from
  your own note about it.
- **"Limited preview: only the title could be read"** when a page gives almost
  nothing, for example an app that draws itself with JavaScript.
- **On the note page,** the Source section shows the card: "Recipe · read from
  the page, not by AI", the site and facts, the ingredients and steps, and the
  description.

### Text only (decision I)

- **No pictures or players are ever loaded:** no thumbnails, no embedded
  YouTube player. oEmbed's thumbnail and player code are discarded, never
  stored.

### A link saved again reuses its earlier result

- **Same tidy link, read successfully before?** The new note takes what was
  read the first time. There's no fetch.
- **With no new note of yours** (or the same one), it's also filed exactly like
  the first, so there's no AI call either: "You saved this link before: Life
  Inbox reused what it read and filed it the same way (no AI call)."
- **With a new note of yours,** it's filed again (1 call), because your purpose
  can change where it goes (rule R3). For example, "cook this for my date"
  sends a recipe to Occasions & gifts.
- **Only your own links are reused,** never another account's.

### Privacy page

- **It now says** that the server asks YouTube's or Vimeo's oEmbed for a
  video's title and channel, reads the facts pages publish for search engines,
  and removes tracking parts. It also says saved links are shown as text only.

### API and data

- **`POST /api/items/url`** saves the tidy link. The note it returns carries:
  - `link_card`;
  - for a link saved again, `reused_from` (the earlier note) and
    `filing_reused` (filed the same way, no AI call).
- **Migration `0024_link_cards`** adds `inbox_items.link_card`. It can't be
  undone automatically.
- **New in `app/capture/link_card.py`:** tidying, oEmbed, the page reader, the
  card. `fetch_url` now hands the page to the reader in memory; only the card
  is stored.

## The owner's database

- **Trial on a copy,** then a backup to
  `data/life_inbox.backup-2026-11-08-pre-0024.db`, then 0023 → 0024. Done before
  the code needing it was saved.
- **Row counts unchanged:** 2 users, 26 notes, 26 insights, 26 tasks, 36
  topics, 34 analysis runs. Integrity check OK, and the server healthy.
- **Links saved before this change have no card.** Their source stays their
  page text. Saving such a link again reuses it as it is. A card is built the
  next time a link is read (a new link, or Retry).

## Files changed

| File | Change |
|---|---|
| `migrations/versions/0024_link_cards.py` | **New.** The link card column |
| `app/capture/link_card.py` | **New.** Tidy links, oEmbed, the page reader (structured data, main text), the card |
| `app/capture/url_fetch.py` | Hands the fetched page to the card reader |
| `app/database.py` | The card is stored and shown; a link's source for filing is its card; finding and reusing a link saved before |
| `app/main.py`, `app/schemas.py` | Tidy before saving; build the card; reuse a link saved before; `link_card`, `reused_from`, `filing_reused` |
| `app/static/app.js` | "You saved this link before…", and no filing call when it was reused |
| `app/static/shell.js`, `app/static/shell.css`, `app/templates/index.html` | The card on the note page; asset version `20261108_links1` |
| `app/templates/privacy.html` | oEmbed, structured data, tidy links, text only |
| `tests/test_link_cards.py` | **New.** 12 tests on saved test pages, never the internet |
| `tests/conftest.py` | oEmbed requests are blocked in every test |
| `tests/test_migrations.py` | Head is 0024; the new column |

## How it was tested

- **Full test suite:** 380 passed (12 new; 368 before).
- **New tests (`tests/test_link_cards.py`)**, on saved test pages with no real
  internet. `fetch_url` and the address check are faked, and conftest blocks
  oEmbed:
  - **tidy links:** `utm_*`, `si`, `fbclid` and `gclid` removed; `youtu.be` and
    `m.youtube.com` made canonical; `t` kept;
  - **a YouTube link:** the exact title and channel from a faked oEmbed reply,
    the tidy link stored, and no thumbnail or player kept;
  - **a recipe page:** ingredients, steps, "1 h 30 min" and servings. The menu,
    cookie banner and footer are left out, and the main text after an unclosed
    tag is still read;
  - **an article:** headline, date and author; the subscribe header, consent
    pop-up and "related" box left out;
  - **an event:** date and place;
  - **a page that gives almost nothing:** "Limited preview";
  - **a blocked page (403):** a capture that couldn't be read, with its Needs
    you card (013);
  - **filing's view:** the card is at most 1,500 characters, and it's the
    filing note's source, apart from your words;
  - **a link saved again:**
    - read once, and filed the same way with no AI call;
    - with a new note of yours it's filed again, and your purpose wins (R3);
    - never shared between accounts;
  - **migration 0024:** the column exists.
- **In the browser, on a throwaway server,** with no internet. A made-up recipe
  link was put in the throwaway database with its card built by the real page
  reader:
  - **saving the same link with `?utm_source=whatsapp`** stored the tidy link,
    said "You saved this link before… (no AI call)", made no filing call, and
    filed it like the first;
  - **the note page** showed the recipe card: site, time, servings,
    ingredients, steps and description, marked "read from the page, not by AI";
  - no script errors.
- **Fixed during the check:** recipe times showed the page's raw "PT1H30M".
  They now read "1 h 30 min".

## Before pushing

- **A database upgrade is needed:** `python -m alembic upgrade head` adds
  `0024_link_cards`. Back up first.

## Known limits

- **No YouTube API key (decision H):** a video's card has its title, channel
  and the page's description, but not its full description or chapters. A key
  can be added later.
- **No transcripts,** and no on-demand "Summarize in depth". Both are optional
  and for later, as the plan says.
- **Sites that need JavaScript or a sign-in** give a limited preview.
- **Cards are built when a link is read.** Older links get one only if read
  again.
