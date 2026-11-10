"""Change 021: text in images (Tesseract, faked here) and the vision call
for images with no text and no note (decision O; the AI is always faked)."""

import importlib
import json
import sys
import types
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register
from tests.image_fixtures import make_png_bytes

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'images.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("LIFE_INBOX_DISABLE_OCR", raising=False)
    monkeypatch.delenv("LIFE_INBOX_DISABLE_VISION", raising=False)
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    with TestClient(main.app) as test_client:
        register(test_client, "owner@example.com")
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def fake_tesseract(monkeypatch, text="", missing=False):
    """A stand-in pytesseract: returns `text`, or raises TesseractNotFoundError."""
    seen = {}

    class TesseractNotFoundError(EnvironmentError):
        pass

    def image_to_string(image, config=""):
        seen["size"], seen["mode"], seen["config"] = image.size, image.mode, config
        if missing:
            raise TesseractNotFoundError("tesseract is not installed or it's not in your PATH")
        return text

    module = types.ModuleType("pytesseract")
    module.image_to_string = image_to_string
    module.TesseractNotFoundError = TesseractNotFoundError
    module.pytesseract = SimpleNamespace(tesseract_cmd="tesseract")
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    return seen, module


def fake_vision(monkeypatch, answer, calls):
    import openai

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


def upload(client, context=None):
    files = {"file": ("IMG_2041.png", make_png_bytes(text=" "), "image/png")}
    response = client.post("/api/items/image", files=files, data={"context": context} if context else {})
    assert response.status_code == 200, response.text
    return response.json()


VISION = json.dumps({"title": "Sunset over a lake", "description": "A sunset over a calm lake with trees.", "kind": "photo"})


# --- OCR -------------------------------------------------------------------------------------------


def test_ocr_reads_text_from_a_prepared_image(monkeypatch):
    from app.capture import image_extract

    seen, _ = fake_tesseract(monkeypatch, text="Wifi:  Hostel-5G\n\n  Router in room 12  \n")
    result = image_extract.run_ocr(make_png_bytes(text="Wifi"))
    assert result == {"text": "Wifi:  Hostel-5G\n  Router in room 12", "provider": "tesseract", "available": True, "note": None}
    assert seen["mode"] == "L" and seen["size"] == (480, 160)  # grey, and a small screenshot doubled
    assert "--psm 3" in seen["config"]


def test_ocr_says_plainly_when_tesseract_is_missing(monkeypatch):
    from app.capture import image_extract

    fake_tesseract(monkeypatch, missing=True)
    result = image_extract.run_ocr(make_png_bytes())
    assert result["available"] is False and result["text"] == ""
    assert result["note"].startswith("Text in images isn't read yet: Tesseract isn't installed")


def test_the_tesseract_path_can_be_set(monkeypatch, tmp_path):
    from app.capture import image_extract

    exe = tmp_path / "tesseract.exe"
    exe.write_text("")
    monkeypatch.setenv("LIFE_INBOX_TESSERACT_CMD", str(exe))
    _, module = fake_tesseract(monkeypatch, text="Hello")
    image_extract.run_ocr(make_png_bytes())
    assert module.pytesseract.tesseract_cmd == str(exe)


# --- the vision call (decision O) ---------------------------------------------------------------------


def test_an_image_with_no_text_and_no_note_gets_one_vision_call(client, monkeypatch):
    fake_tesseract(monkeypatch, text="")
    calls = []
    fake_vision(monkeypatch, VISION, calls)
    item = upload(client)
    assert len(calls) == 1
    content = calls[0]["messages"][0]["content"]
    assert content[1]["type"] == "image_url" and content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert calls[0]["model"] == "meta/llama-3.2-11b-vision-instruct"
    assert item["ai_description"] == "A sunset over a calm lake with trees."
    assert item["title"] == "Sunset over a lake"
    assert item["extracted_text"] in ("", None)  # the AI's words never pose as the image's text
    assert "[AI description — inferred]" in item["raw_text"]


def test_no_vision_call_with_text_a_note_no_ai_or_the_switch_off(client, monkeypatch):
    calls = []
    fake_tesseract(monkeypatch, text="Exam timetable: Monday maths, Tuesday physics")
    fake_vision(monkeypatch, VISION, calls)
    with_text = upload(client)
    assert calls == [] and "Exam timetable" in with_text["extracted_text"]

    fake_tesseract(monkeypatch, text="")
    upload(client, context="My cousin's wedding venue")
    assert calls == []  # your note says what it is

    client.patch("/api/settings", json={"ai_processing": False})
    upload(client)
    assert calls == []
    client.patch("/api/settings", json={"ai_processing": True})

    monkeypatch.delenv("NVIDIA_API_KEY")
    plain = upload(client)
    assert calls == [] and plain["ai_description"].startswith("Uploaded PNG image")


def test_a_bad_vision_answer_falls_back_to_the_local_description(client, monkeypatch):
    fake_tesseract(monkeypatch, text="")
    calls = []
    fake_vision(monkeypatch, "not json at all", calls)
    item = upload(client)
    assert len(calls) == 1
    assert item["processing_status"] == "ready"
    assert item["ai_description"].startswith("Uploaded PNG image")


def test_the_vision_model_can_be_chosen(monkeypatch):
    from app.capture import image_extract

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")
    monkeypatch.setenv("LIFE_INBOX_VISION_MODEL", "some/vision-model")
    assert image_extract.vision_model() == "some/vision-model"
    assert image_extract.needs_vision("", None) and image_extract.needs_vision("ok", "")
    assert not image_extract.needs_vision("Three real words", None)
    assert not image_extract.needs_vision("", "my note")
