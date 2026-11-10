"""Image / screenshot validation, OCR, and description adapters."""

from __future__ import annotations

import io
import logging
import os
import re
from pathlib import Path
from typing import Optional

from app.capture.storage import MAX_IMAGE_BYTES

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
ALLOWED_IMAGE_MIMES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
}

# Magic / signature sniffing for common image types.
_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
    (b"RIFF", "image/webp", ".webp"),  # refined below
]


def _normalize_filename(filename: str) -> str:
    name = Path(filename or "image.png").name
    if not name or name in {".", ".."}:
        return "image.png"
    return name


def _sniff_image(data: bytes) -> tuple[str, str]:
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    for magic, mime, ext in _SIGNATURES:
        if magic != b"RIFF" and data.startswith(magic):
            return mime, ext
    raise ValueError("File does not look like a supported image (PNG/JPEG/WebP/GIF).")


def validate_image_upload(
    filename: str,
    content_type: Optional[str],
    data: bytes,
) -> tuple[str, str, str]:
    """Validate upload; return (safe_filename, detected_mime, storage_extension)."""
    safe_name = _normalize_filename(filename)
    suffix = Path(safe_name).suffix.lower()
    if suffix and suffix not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError(
            "Only PNG, JPEG, WebP, or GIF images are allowed."
        )

    if not data:
        raise ValueError("Uploaded file is empty.")

    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(
            f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)} MB upload limit."
        )

    detected_mime, detected_ext = _sniff_image(data)

    if content_type:
        mime = content_type.split(";", 1)[0].strip().lower()
        if mime and mime not in ALLOWED_IMAGE_MIMES:
            raise ValueError(
                "Unsupported content type. Upload a PNG, JPEG, WebP, or GIF image."
            )

    if suffix and suffix != detected_ext:
        # Prefer sniffed type; keep original filename for display.
        pass

    return safe_name, detected_mime, detected_ext


def _title_from_filename(filename: str) -> str:
    stem = Path(filename).stem.strip()
    return stem or "Image capture"


def make_thumbnail_bytes(data: bytes, *, max_size: int = 320) -> bytes:
    """Create a JPEG thumbnail; raises ValueError if the image cannot be opened."""
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError(
            "Image processing is unavailable (Pillow not installed)."
        ) from exc

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGB")
            image.thumbnail((max_size, max_size))
            out = io.BytesIO()
            image.save(out, format="JPEG", quality=85)
            return out.getvalue()
    except Exception as exc:
        raise ValueError("Unable to read this image for preview.") from exc


# Change 021: where Tesseract is (the owner installs it; see docs/deployment.md).
_TESSERACT_PLACES = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)
NOT_INSTALLED = ("Text in images isn't read yet: Tesseract isn't installed on this computer "
                 "(see docs/deployment.md, \"Reading text in images\").")


def tesseract_cmd() -> Optional[str]:
    """LIFE_INBOX_TESSERACT_CMD, else the usual Windows install places, else
    None (pytesseract then looks on PATH)."""
    chosen = os.getenv("LIFE_INBOX_TESSERACT_CMD", "").strip()
    if chosen:
        return chosen
    local = os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs", "Tesseract-OCR", "tesseract.exe")
    for place in (*_TESSERACT_PLACES, local):
        if place and os.path.isfile(place):
            return place
    return None


def _prepare_for_ocr(image):
    """Screenshots read better upright, in grey, and not tiny."""
    from PIL import ImageOps

    image = ImageOps.exif_transpose(image).convert("L")
    if max(image.size) < 1200:
        image = image.resize((image.width * 2, image.height * 2))
    return image


def run_ocr(data: bytes) -> dict:
    """OCR adapter. Graceful when Tesseract/pytesseract is unconfigured.

    Returns:
        {"text": str, "provider": str, "available": bool, "note": str | None}
    """
    if os.getenv("LIFE_INBOX_DISABLE_OCR", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return {
            "text": "",
            "provider": "disabled",
            "available": False,
            "note": "OCR disabled via LIFE_INBOX_DISABLE_OCR.",
        }

    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return {
            "text": "",
            "provider": "none",
            "available": False,
            "note": "OCR not configured (install Pillow + pytesseract + Tesseract).",
        }

    command = tesseract_cmd()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    try:
        with Image.open(io.BytesIO(data)) as image:
            text = pytesseract.image_to_string(_prepare_for_ocr(image), config="--oem 3 --psm 3") or ""
        cleaned = "\n".join(
            line.rstrip() for line in text.splitlines() if line.strip()
        ).strip()
        return {
            "text": cleaned,
            "provider": "tesseract",
            "available": True,
            "note": None if cleaned else "OCR ran but found no text.",
        }
    except Exception as exc:
        if type(exc).__name__ == "TesseractNotFoundError":
            return {"text": "", "provider": "none", "available": False, "note": NOT_INSTALLED}
        logger.info("OCR failed gracefully: %s", exc)
        return {
            "text": "",
            "provider": "tesseract",
            "available": False,
            "note": f"OCR unavailable: {exc}",
        }


def vision_model() -> str:
    """The model for the vision call: LIFE_INBOX_VISION_MODEL, else a vision
    model of the configured provider."""
    from app import llm

    chosen = os.getenv("LIFE_INBOX_VISION_MODEL", "").strip()
    if chosen:
        return chosen
    return "meta/llama-3.2-11b-vision-instruct" if llm.provider() == "nvidia_nim" else "gpt-4o-mini"


def needs_vision(ocr_text: str, user_context: Optional[str]) -> bool:
    """Decision O: only an image with no readable text and no note of yours."""
    words = re.findall(r"[A-Za-z0-9]{2,}", ocr_text or "")
    return len(words) < 3 and not (user_context or "").strip()


def _vision_description(data: bytes, original_filename: str) -> Optional[dict]:
    """One vision call (through app/llm.py) for what the image shows. None on
    any failure: the local description is used instead."""
    import base64

    from app import llm

    small = make_thumbnail_bytes(data, max_size=768)
    picture = "data:image/jpeg;base64," + base64.b64encode(small).decode("ascii")
    messages = [{"role": "user", "content": [
        {"type": "text", "text": (
            "Describe this saved image for a personal notes app, in JSON only: "
            '{"title": "3-8 word title", "description": "one or two plain sentences of what it shows", '
            '"kind": "photo|screenshot|document|diagram|other"}. Say only what is visible; '
            "don't guess names, places or intentions.")},
        {"type": "image_url", "image_url": {"url": picture}},
    ]}]
    try:
        answer = llm.complete_text("image_vision", messages=messages, model=vision_model(), temperature=0.1)
        data_out = llm.extract_json_object(answer)
    except Exception as exc:
        logger.info("Vision description failed; using the local one: %s", type(exc).__name__)
        return None
    description = " ".join(str(data_out.get("description") or "").split())[:400]
    title = " ".join(str(data_out.get("title") or "").split())[:80]
    if not description:
        return None
    return {"description": description, "title": title or None, "provider": "vision", "inferred": True,
            "kind": str(data_out.get("kind") or "other")[:20]}


def describe_image(
    *,
    original_filename: str,
    mime_type: str,
    ocr_text: str,
    ocr_note: Optional[str],
    data: Optional[bytes] = None,
    user_context: Optional[str] = None,
    allow_vision: bool = False,
) -> dict:
    """Factual-ish description adapter. Distinguishes inferred content.

    Change 021 (decision O): one vision call when the image has no readable
    text and no note of yours, AI is set up and allowed for you. Otherwise a
    deterministic local summary, so tests and offline runs never pay.
    """
    if os.getenv("LIFE_INBOX_DISABLE_VISION", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return _fallback_description(
            original_filename, mime_type, ocr_text, ocr_note
        )

    if allow_vision and data and needs_vision(ocr_text, user_context):
        from app import llm

        if llm.is_configured():
            described = _vision_description(data, original_filename)
            if described is not None:
                return described

    return _fallback_description(
        original_filename, mime_type, ocr_text, ocr_note
    )


def _fallback_description(
    original_filename: str,
    mime_type: str,
    ocr_text: str,
    ocr_note: Optional[str],
) -> dict:
    kind = "screenshot or photo"
    if mime_type == "image/png":
        kind = "PNG image (often a screenshot)"
    elif mime_type in {"image/jpeg", "image/jpg"}:
        kind = "JPEG photo/image"
    elif mime_type == "image/webp":
        kind = "WebP image"
    elif mime_type == "image/gif":
        kind = "GIF image"

    parts = [
        f"Uploaded {kind} named “{original_filename}”.",
    ]
    if ocr_text:
        preview = ocr_text.replace("\n", " ").strip()
        if len(preview) > 160:
            preview = preview[:157] + "…"
        parts.append(f"OCR found readable text starting with: {preview}")
    elif ocr_note:
        parts.append(f"OCR note: {ocr_note}")
    else:
        parts.append("No OCR text was extracted.")

    parts.append(
        "Suggested category: Media / Screenshots. "
        "Possible actions: review text, file under a topic, or create a follow-up task."
    )
    return {
        "description": " ".join(parts),
        "provider": "local_fallback",
        "inferred": True,
    }


def process_image_bytes(
    data: bytes,
    *,
    original_filename: str,
    mime_type: str,
    user_context: Optional[str] = None,
    allow_vision: bool = False,
) -> dict:
    """Run thumbnail + OCR + description. Always returns a processable result."""
    # Thumbnail generation validates the image is readable.
    thumbnail = make_thumbnail_bytes(data)
    ocr = run_ocr(data)
    description = describe_image(
        original_filename=original_filename,
        mime_type=mime_type,
        ocr_text=ocr["text"],
        ocr_note=ocr.get("note"),
        data=data,
        user_context=user_context,
        allow_vision=allow_vision,
    )
    title = description.get("title") or _title_from_filename(original_filename)
    ocr_text = ocr["text"]
    ai_description = description["description"]

    # Searchable combined body: facts first, then clearly labeled inference.
    raw_parts = []
    if ocr_text:
        raw_parts.append(ocr_text)
    raw_parts.append(f"[AI description — inferred]\n{ai_description}")
    raw_text = "\n\n".join(raw_parts)

    return {
        "title": title,
        "raw_text": raw_text,
        "extracted_text": ocr_text,
        "ai_description": ai_description,
        "mime_type": mime_type,
        "thumbnail_bytes": thumbnail,
        "ocr_provider": ocr["provider"],
        "ocr_available": ocr["available"],
        "ocr_note": ocr.get("note"),
        "description_inferred": True,
        "description_provider": description.get("provider"),
    }
