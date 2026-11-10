"""PDF upload validation and text extraction.

Change 022: formulas keep their lines (pypdf's layout mode; ligatures fixed,
symbols such as ², √ and ≤ kept); scanned pages (no text layer) are rendered
with pypdfium2 and read by OCR, at most OCR_PAGE_LIMIT of them; a long PDF
gets one AI summary when it's read (decision P), kept apart as AI output.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

from pypdf import PdfReader

from app.capture.storage import MAX_PDF_BYTES

logger = logging.getLogger(__name__)

PDF_MAGIC = b"%PDF"
OCR_PAGE_LIMIT = 10
SCANNED_PAGE_CHARS = 20
LONG_PDF_CHARS = 6000
LONG_PDF_PAGES = 5
SUMMARY_INPUT_CHARS = 9000
_LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\u00ad": ""}
SCANNED_HINT = (" Text in scans is read once Tesseract is installed "
                "(see docs/deployment.md, \"Reading text in images\").")
ALLOWED_PDF_MIMES = {
    "application/pdf",
    "application/x-pdf",
}


def _normalize_filename(filename: str) -> str:
    name = Path(filename or "document.pdf").name
    if not name or name in {".", ".."}:
        return "document.pdf"
    return name


def validate_pdf_upload(
    filename: str,
    content_type: Optional[str],
    data: bytes,
) -> str:
    """Validate upload bytes; return sanitized original filename."""
    safe_name = _normalize_filename(filename)
    if not safe_name.lower().endswith(".pdf"):
        raise ValueError("Only .pdf files are allowed.")

    if not data:
        raise ValueError("Uploaded file is empty.")

    if len(data) > MAX_PDF_BYTES:
        raise ValueError(
            f"PDF exceeds the {MAX_PDF_BYTES // (1024 * 1024)} MB upload limit."
        )

    if not data.startswith(PDF_MAGIC):
        raise ValueError("File does not look like a valid PDF.")

    if content_type:
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime and mime not in ALLOWED_PDF_MIMES:
            raise ValueError(
                "Unsupported content type. Upload a PDF (application/pdf)."
            )

    return safe_name


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or "PDF document"


def extract_pdf_text(
    data: bytes,
    *,
    original_filename: Optional[str] = None,
) -> dict:
    """Extract text and metadata from PDF bytes."""
    reader = PdfReader(BytesIO(data))
    if reader.is_encrypted:
        raise ValueError(
            "This PDF is password-protected or encrypted and cannot be read."
        )

    meta_title = None
    if reader.metadata and reader.metadata.title:
        meta_title = str(reader.metadata.title).strip() or None

    parts: list[str] = []
    scanned: list[int] = []
    for number, page in enumerate(reader.pages):
        try:
            cleaned = clean_page_text(_page_text(page))
        except Exception as exc:
            raise ValueError("Unable to read text from this PDF.") from exc
        if len(cleaned) >= SCANNED_PAGE_CHARS:
            parts.append(cleaned)
        else:
            scanned.append(number)
            parts.append("")

    ocr_pages, ocr_note = read_scanned_pages(data, scanned) if scanned else ({}, None)
    for number, text in ocr_pages.items():
        parts[number] = f"[Page {number + 1}, read by OCR]\n{text}"

    extracted = "\n\n".join(part for part in parts if part).strip()
    if not extracted:
        raise ValueError(
            "No extractable text found. This PDF may be scanned or image-only."
            + (SCANNED_HINT if ocr_note else "")
        )

    title = meta_title or _title_from_filename(original_filename or "document.pdf")
    return {
        "title": title,
        "raw_text": extracted,
        "extracted_text": extracted,
        "mime_type": "application/pdf",
        "pages": len(reader.pages),
        "ocr_pages": sorted(number + 1 for number in ocr_pages),
        "ocr_note": ocr_note,
    }


def _page_text(page) -> str:
    """A page's text with its layout (formulas keep their lines), else plain."""
    try:
        text = page.extract_text(extraction_mode="layout") or ""
    except TypeError:  # an older pypdf
        text = ""
    except Exception:
        text = ""
    return text or (page.extract_text() or "")


def clean_page_text(text: str) -> str:
    """Lines kept; spaces inside a line collapsed; ligatures fixed; blank runs cut."""
    for char, plain in _LIGATURES.items():
        text = text.replace(char, plain)
    lines = [re.sub(r"[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    return "\n".join(out).strip()


def read_scanned_pages(data: bytes, pages: list[int]) -> tuple[dict[int, str], Optional[str]]:
    """OCR for pages with no text layer (rendered with pypdfium2). Returns the
    text per page, and a note when OCR isn't available."""
    from app.capture.image_extract import NOT_INSTALLED, run_ocr

    try:
        import pypdfium2
    except ImportError:
        return {}, "Scanned pages can't be read: pypdfium2 isn't installed."
    found: dict[int, str] = {}
    note = None
    try:
        document = pypdfium2.PdfDocument(data)
    except Exception as exc:
        logger.info("Couldn't render this PDF for OCR: %s", type(exc).__name__)
        return {}, "Scanned pages couldn't be rendered for OCR."
    try:
        for number in pages[:OCR_PAGE_LIMIT]:
            bitmap = document[number].render(scale=200 / 72)
            image = bitmap.to_pil()
            out = BytesIO()
            image.save(out, format="PNG")
            result = run_ocr(out.getvalue())
            if not result["available"]:
                note = result.get("note") or NOT_INSTALLED
                break
            if result["text"].strip():
                found[number] = clean_page_text(result["text"])
    finally:
        document.close()
    return found, note


def is_long(extracted: dict) -> bool:
    return len(extracted.get("extracted_text") or "") > LONG_PDF_CHARS or (extracted.get("pages") or 0) > LONG_PDF_PAGES


def summarize_pdf(extracted: dict) -> Optional[str]:
    """Decision P: one AI summary of a long PDF, made once when it's read.
    Sends the start of the text and the headings after it (secrets masked).
    None when the call fails (the PDF is still saved)."""
    from app import llm
    from app.sensitive import mask_secrets

    text = mask_secrets(extracted.get("extracted_text") or "")
    head = text[:SUMMARY_INPUT_CHARS]
    rest = text[SUMMARY_INPUT_CHARS:]
    headings = [line for line in rest.splitlines()
                if 3 <= len(line) <= 80 and (re.match(r"^(\d+(\.\d+)*\.?|[IVX]+\.|Chapter|Section|Unit)\s", line)
                                            or line.isupper())][:40]
    prompt = f"""Summarise this document for a personal notes app, so it can be filed and found later.

Title: {extracted.get("title") or ""}
Pages: {extracted.get("pages") or "?"}

The start of the text:
{head}

Headings further on:
{chr(10).join(headings) or "(none)"}

Answer with ONLY this JSON: {{"summary": "4-6 plain sentences on what the document covers and is for"}}
Use only the text above. No advice, no invented facts."""
    out: dict = {}

    def validate(data: dict) -> Optional[str]:
        value = " ".join(str((data or {}).get("summary") or "").split())
        if not value or len(value) > 1400:
            return "\"summary\" must be 4-6 sentences, under 1,200 characters."
        out["summary"] = value
        return None

    try:
        llm.complete_json("pdf_summary", prompt, validate=validate, repair=True)
    except Exception:
        logger.exception("PDF summary failed; the PDF is saved without one")
        return None
    return out.get("summary")
