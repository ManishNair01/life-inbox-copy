"""Changes 022 and 023: PDFs with formulas and scans, a long PDF's one-time
summary (decision P), and editing your note on a saved source. OCR and the AI
are always faked."""

import importlib
import json
import sys
import types
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register
from tests.test_filing import entry, notes_in

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sources.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_DISABLE_OCR", "1")
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    monkeypatch.setattr(importlib.import_module("app.llm"), "RETRY_DELAY_SECONDS", 0)
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com")
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def build_pdf(pages):
    """A real multi-page PDF: each page a list of text lines, or None for a
    page with no text layer (as a scan has)."""
    objects = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
               3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    for index, lines in enumerate(pages):
        page, content = 4 + 2 * index, 5 + 2 * index
        kids.append(f"{page} 0 R")
        stream = b""
        if lines:
            body = " T* ".join("(" + line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ") Tj"
                               for line in lines)
            stream = f"BT /F1 11 Tf 14 TL 72 740 Td {body} ET".encode("latin-1")
        objects[page] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                         f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content} 0 R >>").encode()
        objects[content] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>".encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += f"trailer << /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def fake_tesseract(monkeypatch, text):
    module = types.ModuleType("pytesseract")
    module.image_to_string = lambda image, config="": text
    module.TesseractNotFoundError = type("TesseractNotFoundError", (EnvironmentError,), {})
    module.pytesseract = SimpleNamespace(tesseract_cmd="tesseract")
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    monkeypatch.delenv("LIFE_INBOX_DISABLE_OCR", raising=False)


def fake_ai(monkeypatch, decide, prompts):
    import openai

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        prompts.append(prompt)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(decide(prompt))))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


def upload_pdf(client, data, name="notes.pdf", context=None):
    response = client.post("/api/items/pdf", files={"file": (name, data, "application/pdf")},
                           data={"context": context} if context else {})
    assert response.status_code == 200, response.text
    return response.json()


# --- 022: formulas and scans ----------------------------------------------------------------------


def test_page_text_keeps_its_lines_and_fixes_ligatures():
    from app.capture.pdf_extract import clean_page_text

    raw = "Pythagoras:   a2 + b2 = c2  \n\n\n\n  E  =  mc²\nﬁnal ﬂow"
    assert clean_page_text(raw) == "Pythagoras: a2 + b2 = c2\n\nE = mc²\nfinal flow"


def test_a_formula_pdf_keeps_one_line_per_line(client):
    item = upload_pdf(client, build_pdf([["Pythagoras theorem", "a2 + b2 = c2", "Area of a circle = pi r2"]]))
    assert item["processing_status"] == "ready"
    lines = [line for line in item["extracted_text"].splitlines() if line.strip()]
    assert any("a2 + b2 = c2" in line for line in lines)
    assert not any("theorem" in line and "c2" in line for line in lines)  # not squashed into one line


def test_a_scanned_page_is_read_by_ocr(client, monkeypatch):
    fake_tesseract(monkeypatch, "Handwritten notes on hypothesis testing")
    item = upload_pdf(client, build_pdf([["Statistics unit 3, typed page"], None]))
    assert item["processing_status"] == "ready"
    assert "Statistics unit 3" in item["extracted_text"]
    assert "[Page 2, read by OCR]\nHandwritten notes on hypothesis testing" in item["extracted_text"]


def test_a_scan_without_tesseract_says_how_to_read_it(client, monkeypatch):
    module = types.ModuleType("pytesseract")

    class TesseractNotFoundError(EnvironmentError):
        pass

    def missing(image, config=""):
        raise TesseractNotFoundError("not installed")

    module.image_to_string, module.TesseractNotFoundError = missing, TesseractNotFoundError
    module.pytesseract = SimpleNamespace(tesseract_cmd="tesseract")
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    monkeypatch.delenv("LIFE_INBOX_DISABLE_OCR", raising=False)
    item = upload_pdf(client, build_pdf([None, None]))
    assert item["processing_status"] == "failed"
    assert "image-only" in item["error_message"] and "Tesseract" in item["error_message"]


# --- 022: the one-time summary (decision P) -------------------------------------------------------------


def long_pdf():
    return build_pdf([[f"Chapter {page}: Hypothesis testing, part {page}", "Null and alternative hypotheses.",
                       "A t-test compares two means; p-values measure evidence."] for page in range(1, 8)])


def test_a_long_pdf_gets_one_summary_and_filing_sees_it_first(client, monkeypatch):
    prompts = []

    def decide(prompt):
        if "Summarise this document" in prompt:
            return {"summary": "A seven-chapter guide to hypothesis testing: null and alternative hypotheses, t-tests and p-values."}
        return {"notes": [entry(note["id"], "Study", "learn") for note in notes_in(prompt)]}

    fake_ai(monkeypatch, decide, prompts)
    item = upload_pdf(client, long_pdf(), name="stats.pdf")
    assert item["source_summary"].startswith("A seven-chapter guide")
    assert sum("Summarise this document" in p for p in prompts) == 1
    client.post("/api/analyze", params={"item_id": item["id"]})
    filing = [p for p in prompts if "Notes (JSON):" in p][-1]
    assert notes_in(filing)[0]["source"]["text"].startswith("Summary (AI): A seven-chapter guide")
    # Re-filing never makes another summary.
    client.post("/api/analyze", params={"item_id": item["id"]})
    assert sum("Summarise this document" in p for p in prompts) == 1


def test_short_pdfs_and_no_ai_get_no_summary(client, monkeypatch):
    prompts = []
    fake_ai(monkeypatch, lambda prompt: {"summary": "x"}, prompts)
    short = upload_pdf(client, build_pdf([["A one-page receipt for the hostel fees."]]))
    assert short["source_summary"] is None and not any("Summarise" in p for p in prompts)
    client.patch("/api/settings", json={"ai_processing": False})
    long = upload_pdf(client, long_pdf())
    assert long["source_summary"] is None and not any("Summarise" in p for p in prompts)


# --- 023: edit your note on a saved source ------------------------------------------------------------


def test_editing_your_note_on_a_source_refiles_it_from_your_words(client, monkeypatch):
    item = upload_pdf(client, build_pdf([["Hypothesis testing practice set"]]), context="for Statistics")
    prompts = []
    fake_ai(monkeypatch, lambda prompt: {"notes": [entry(note["id"], "Study", "learn") for note in notes_in(prompt)]}, prompts)
    response = client.patch(f"/api/items/{item['id']}/context", json={"context": "revise this before Friday's quiz"})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["refiled"] is True and result["item"]["user_context"] == "revise this before Friday's quiz"
    [prompt] = [p for p in prompts if "Notes (JSON):" in p]
    assert notes_in(prompt)[0]["your_words"] == "revise this before Friday's quiz"

    removed = client.patch(f"/api/items/{item['id']}/context", json={"context": "  "}).json()
    assert removed["item"]["user_context"] is None


def test_only_your_own_sources_can_have_their_note_edited(client):
    text = client.post("/api/items", json={"raw_text": "A plain note"}).json()
    assert client.patch(f"/api/items/{text['id']}/context", json={"context": "x"}).status_code == 404
    assert client.patch("/api/items/9999/context", json={"context": "x"}).status_code == 404
    item = upload_pdf(client, build_pdf([["Receipt"]]))
    assert client.patch(f"/api/items/{item['id']}/context", json={"context": "x" * 2001}).status_code == 422
    client.post("/api/auth/logout")
    register(client, "someone@example.com")
    assert client.patch(f"/api/items/{item['id']}/context", json={"context": "mine now"}).status_code == 404
