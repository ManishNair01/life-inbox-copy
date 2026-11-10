# 021–023: Better sources (Phase 6)

**Date:** 2026-11-09 · **Status:** Done, not pushed · **Decisions:**
- **O (yes):** one vision call for an image with no text and no note.
- **P (yes):** a one-time summary for a long PDF.
- **OCR:** the Python packages are installed; Tesseract is the owner's to
  install.

## 021: Images, read the text

**OCR with Tesseract**, on this computer.

**Finding Tesseract:**
- `LIFE_INBOX_TESSERACT_CMD`, if set;
- else `C:\Program Files\Tesseract-OCR\` (where `winget install --id
  UB-Mannheim.TesseractOCR -e` puts it), or the per-user install folder;
- else the `PATH`.

**Preparing the image:** turned upright, grey, and doubled in size when small
(screenshots read better). The settings are `--oem 3 --psm 3`.

**Until Tesseract is installed,** an image still saves, and its note says
plainly: "Text in images isn't read yet: Tesseract isn't installed on this
computer (see docs/deployment.md, "Reading text in images")."

**The vision call (decision O):**
- **When:** only for an image with no readable text (fewer than 3 words) and
  no note of yours, and only when AI is set up and your AI switch is on.
- **What's sent:** one call through `app/llm.py`, with a small JPEG (at most
  768 px).
- **What comes back:** a short title and one or two sentences of what's
  visible ("don't guess names, places or intentions").
- **Where it's kept:** in `ai_description`, marked as AI output. It never
  poses as the image's own text (`extracted_text` stays the OCR's).
- **The model:** `LIFE_INBOX_VISION_MODEL`, else
  `meta/llama-3.2-11b-vision-instruct` (NVIDIA NIM) or `gpt-4o-mini`
  (OpenAI).
- **A bad answer** falls back to the local description.
- **Not tried live** (it would spend credits). The model name is NVIDIA's
  published one.

**Docs:**
- `docs/deployment.md` has "Reading text in images": install commands for
  Windows, macOS and Linux, how to check, and the switches.
- The privacy page says only such images are sent.

## 022: PDFs, formulas and scans

**Formulas keep their lines:**
- each page is read with pypdf's layout mode;
- spaces inside a line are collapsed, but lines are kept;
- ligatures (ﬁ, ﬂ) are fixed, and symbols such as ², √ and ≤ are kept.

Before, every page was squashed into one line. The note page shows the text
with its line breaks.

**Scanned pages** (fewer than 20 characters of text):
- rendered with pypdfium2 at 200 dpi and read by OCR, at most 10 pages;
- the text is marked "[Page 2, read by OCR]";
- a PDF that's all scan, without Tesseract, fails with the same "image-only"
  message plus how to fix it.

**The one-time summary (decision P):**
- **Which PDFs:** over 6,000 characters or 5 pages, when AI is allowed.
- **The call:** one call made when the PDF is read, from the first 9,000
  characters plus the headings after them, with secrets masked.
- **What's kept:** 4–6 sentences in a new `inbox_items.source_summary`,
  shown on the note page as "Summary of the whole document (AI, made once
  when you saved it)".
- **Filing reads it** before the start of the text, so a long document is
  filed by what it covers.
- **Re-filing never makes another.**

**Migration `0030_source_summary`** (plain `ADD COLUMN`). The owner's
database:
- trial on a copy (deleted);
- a backup to `data/life_inbox.backup-2026-11-09-pre-0030.db`;
- 0029 → 0030, counts unchanged, integrity OK;
- the server is healthy.

## 023: Edit your note on a saved source

- **"Edit note"** (or "Add a note: why you saved it") on the note page of a
  link, PDF, image or voice note, and **Edit note / Add a note** on its card
  in All notes.
- **Saving** (`PATCH /api/items/{id}/context`) keeps your words and files the
  note again from them (one call, as saving does). A failed re-file never
  loses the edit.
- **Empty removes your note.**
- **Your dates are re-read,** as when a note's text is edited.
- **Only your own sources;** a plain note keeps its own Edit.

## Tests

- **Full suite:** 473 passed.
- **New: `tests/test_images_ocr.py`** (7 tests):
  - OCR reads a prepared image (grey, doubled);
  - a plain message when Tesseract is missing;
  - the Tesseract path can be set;
  - one vision call for an image with no text and no note (the image is sent
    as a JPEG; the description is AI output);
  - no call with text, with a note, without AI, or with the switch off;
  - a bad answer falls back;
  - the vision model can be chosen.
- **New: `tests/test_sources_v2.py`** (9 tests), with real multi-page PDFs
  built in memory:
  - page text keeps its lines;
  - a formula PDF isn't squashed;
  - a scanned page is read by OCR;
  - a scan without Tesseract says how to fix it;
  - a long PDF gets one summary, filing sees it first, and re-filing makes no
    new one;
  - short PDFs and no AI get none;
  - editing your note re-files it from your words;
  - empty removes it;
  - only your own sources can be edited (422 over 2,000 characters).
- **Updated:**
  - the migration head and the `inbox_items` columns;
  - the item shape;
  - the shell test knows the note box.
- **Browser check (throwaway server, port 8018, AI and Tesseract off):**
  - An image saved with the "Tesseract isn't installed" note.
  - A formula PDF kept its three lines on the note page.
  - "Edit note" opened filled in and focused. Saving said "Saved. Filed again
    from your words.", and the new words made a task with a suggested
    Friday.
  - The cards in All notes show "Add a note" / "Edit note".
  - The only console errors were 404s for the filing of two notes uploaded
    straight through the API and never filed: existing behaviour, which the
    screen treats as "not filed yet".
