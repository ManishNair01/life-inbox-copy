"""Link cards (change 015): what code can read from a saved link, before any AI.

- **Tidy links**: tracking parts (utm_*, si, fbclid, gclid...) are removed and
  YouTube's short forms become one canonical link, so a link saved twice is
  recognised and reuses its earlier result (no fetch, no AI call).
- **Free facts**: oEmbed for YouTube and Vimeo (the exact title and channel);
  the page's own structured data (schema.org JSON-LD: an article's headline,
  date and author, a recipe's ingredients and steps, an event's date and
  place); page tags (title, description, site name); and the main text with
  menus, footers and cookie banners left out.
- **The card**: at most 1,500 characters of text, stored on the note apart
  from the AI's output. It's the "source" the filing call sees for a link.
  A page that gives almost nothing gets "Limited preview: only the title
  could be read".

Only the Python standard library parses pages, so there is no extraction
library (or licence) to vet. No pictures or players are ever loaded
(decision I: text only).
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

CARD_TEXT_LIMIT = 1500
LIMITED_BELOW = 160  # characters of real text, besides the title

TRACKING = re.compile(
    r"^(utm_\w+|si|fbclid|gclid|dclid|gbraid|wbraid|yclid|msclkid|igshid|igsh|mc_cid|mc_eid|"
    r"ref_src|ref_url|feature|spm|_ga|_gl|vero_id|mkt_tok|trk|trkCampaign|s_cid|cmpid)$",
    re.I,
)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
OEMBED = {
    "youtube": "https://www.youtube.com/oembed?format=json&url={url}",
    "vimeo": "https://vimeo.com/api/oembed.json?url={url}",
}


def tidy_url(url: str) -> str:
    """The link without tracking parts, in one canonical form."""
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if not TRACKING.match(key)]
    path = parsed.path or "/"
    if host == "youtu.be" and path.strip("/"):
        video = path.strip("/").split("/")[0]
        rest = [(k, v) for k, v in query if k != "v"]
        return urlunparse(("https", "www.youtube.com", "/watch", "", urlencode([("v", video)] + rest), ""))
    if host in YOUTUBE_HOSTS:
        host = "www.youtube.com"
    netloc = host + (f":{parsed.port}" if parsed.port else "")
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return urlunparse(((parsed.scheme or "https").lower(), netloc, path, parsed.params, urlencode(query), ""))


def video_site(url: str) -> Optional[str]:
    host = (urlparse(url).hostname or "").lower()
    if host in YOUTUBE_HOSTS or host == "youtu.be":
        return "youtube"
    if host in {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}:
        return "vimeo"
    return None


def oembed_url(url: str) -> Optional[str]:
    from urllib.parse import quote

    site = video_site(url)
    return OEMBED[site].format(url=quote(url, safe="")) if site else None


# --- reading a page -------------------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "nav", "header", "footer", "aside", "form", "button"}
_SKIP_HINTS = re.compile(r"cookie|consent|gdpr|banner|newsletter|subscribe|popup|modal|nav|menu|footer|sidebar|advert|promo|share|related|comment", re.I)
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _PageReader(HTMLParser):
    """Page tags, JSON-LD blocks and the main text (menus, footers and cookie
    banners left out)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.jsonld: list[str] = []
        self.text: list[str] = []
        self._stack: list[tuple[str, bool]] = []  # open tags, and whether each is skipped
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_parts: list[str] = []

    def _skipping(self) -> bool:
        return any(skip for _, skip in self._stack)

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            name = (attrs.get("property") or attrs.get("name") or "").lower()
            content = attrs.get("content", "").strip()
            if name and content and name not in self.meta:
                self.meta[name] = content
            return
        if tag == "title":
            self._in_title = True
        if tag == "script" and "ld+json" in attrs.get("type", "").lower():
            self._in_jsonld = True
            self._jsonld_parts = []
        if tag in _VOID:
            return
        hint = f"{attrs.get('class', '')} {attrs.get('id', '')} {attrs.get('role', '')}"
        self._stack.append((tag, tag in _SKIP_TAGS or bool(_SKIP_HINTS.search(hint)) or attrs.get("aria-hidden") == "true"))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append("".join(self._jsonld_parts))
        if tag in _VOID:
            return
        # Close back to the matching open tag: pages often leave <p> or <li> open.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break

    def handle_data(self, data):
        if self._in_jsonld:
            self._jsonld_parts.append(data)
            return
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._skipping():
            return
        text = " ".join(data.split())
        if text:
            self.text.append(text)


def _jsonld_objects(blocks: list[str]) -> list[dict]:
    found = []

    def walk(value):
        if isinstance(value, list):
            for entry in value:
                walk(entry)
        elif isinstance(value, dict):
            found.append(value)
            for key in ("@graph", "mainEntity", "itemListElement"):
                if key in value:
                    walk(value[key])

    for block in blocks:
        try:
            walk(json.loads(block.strip()))
        except (ValueError, TypeError):
            continue
    return found


def _types(entry: dict) -> set[str]:
    kind = entry.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return {str(k) for k in kinds if k}


def _duration(value) -> Optional[str]:
    """ISO 8601 durations as people say them: "PT1H30M" is "1 h 30 min"."""
    text = _name(value)
    found = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", text or "", re.I)
    if not text or not found or not any(found.groups()):
        return text
    days, hours, minutes, seconds = (int(part) if part else 0 for part in found.groups())
    parts = [f"{days} d" if days else "", f"{hours} h" if hours else "", f"{minutes} min" if minutes else "",
             f"{seconds} s" if seconds and not (days or hours) else ""]
    return " ".join(part for part in parts if part)


def _name(value) -> Optional[str]:
    if isinstance(value, list):
        names = [_name(v) for v in value]
        return ", ".join(n for n in names if n) or None
    if isinstance(value, dict):
        return _name(value.get("name") or value.get("text") or value.get("address"))
    text = " ".join(str(value or "").split())
    return text or None


def _steps(instructions) -> list[str]:
    steps = []
    if isinstance(instructions, str):
        steps = [part.strip() for part in re.split(r"(?:\r?\n)+|(?<=\.)\s+(?=[A-Z])", instructions) if part.strip()]
    elif isinstance(instructions, list):
        for entry in instructions:
            if isinstance(entry, dict) and entry.get("itemListElement"):
                steps.extend(_steps(entry["itemListElement"]))
            elif isinstance(entry, (dict, str)):
                text = _name(entry)
                if text:
                    steps.append(text)
    return steps


def structured_facts(blocks: list[str]) -> dict:
    """Facts from the page's own schema.org data: recipe, article, event, video."""
    for entry in _jsonld_objects(blocks):
        kinds = _types(entry)
        if "Recipe" in kinds:
            return {
                "kind": "recipe",
                "title": _name(entry.get("name")),
                "ingredients": [_name(i) for i in (entry.get("recipeIngredient") or []) if _name(i)][:15],
                "steps": _steps(entry.get("recipeInstructions"))[:8],
                "time": _duration(entry.get("totalTime") or entry.get("cookTime")),
                "yield": _name(entry.get("recipeYield")),
            }
        if kinds & {"Event", "MusicEvent", "SportsEvent", "EducationEvent", "BusinessEvent", "SocialEvent"}:
            return {
                "kind": "event",
                "title": _name(entry.get("name")),
                "when": _name(entry.get("startDate")),
                "ends": _name(entry.get("endDate")),
                "where": _name(entry.get("location")),
            }
        if kinds & {"Article", "NewsArticle", "BlogPosting", "Report", "ScholarlyArticle", "TechArticle"}:
            return {
                "kind": "article",
                "title": _name(entry.get("headline") or entry.get("name")),
                "published": _name(entry.get("datePublished")),
                "author": _name(entry.get("author")),
            }
        if "VideoObject" in kinds:
            return {
                "kind": "video",
                "title": _name(entry.get("name")),
                "published": _name(entry.get("uploadDate")),
                "duration": _duration(entry.get("duration")),
            }
    return {}


def read_page(html: str) -> dict:
    reader = _PageReader()
    try:
        reader.feed(html or "")
        reader.close()
    except Exception:
        pass  # malformed HTML still gives what was read
    meta = reader.meta
    return {
        "title": meta.get("og:title") or meta.get("twitter:title") or " ".join("".join(reader.title_parts).split()) or None,
        "description": meta.get("og:description") or meta.get("description") or meta.get("twitter:description"),
        "site": meta.get("og:site_name") or meta.get("application-name"),
        "published": meta.get("article:published_time"),
        "facts": structured_facts(reader.jsonld),
        "text": " ".join(reader.text),
    }


# --- the card ------------------------------------------------------------------------------


def _clip(text: Optional[str], limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: max(0, limit - 1)].rstrip() + "…"


def build_card(url: str, page: Optional[dict] = None, oembed: Optional[dict] = None, *, fallback_title: Optional[str] = None,
               fallback_text: Optional[str] = None) -> dict:
    """The link card: kind, title, site or channel, facts, a short excerpt, and
    its text (at most 1,500 characters), all read by code."""
    page = page or {}
    oembed = oembed or {}
    facts = dict(page.get("facts") or {})
    kind = facts.pop("kind", None) or ("video" if video_site(url) else "page")
    title = _clip(oembed.get("title") or facts.pop("title", None) or page.get("title") or fallback_title or url, 200)
    facts.pop("title", None)
    site = oembed.get("provider_name") or page.get("site") or (urlparse(url).hostname or "").removeprefix("www.")
    channel = oembed.get("author_name")
    description = _clip(page.get("description"), 400)
    main = page.get("text") if page else None
    if not main and fallback_text and fallback_text != title:
        main = fallback_text
    if description and main and main.startswith(description[:60]):
        main = main[len(description):]
    real_text = " ".join(part for part in (description, main) if part).strip()
    limited = len(real_text) < LIMITED_BELOW and not any(facts.values())
    card = {
        "url": url,
        "kind": kind,
        "title": title,
        "site": site,
        "channel": channel,
        "published": facts.pop("published", None) or page.get("published"),
        "facts": {key: value for key, value in facts.items() if value},
        "description": description or None,
        "limited": limited,
    }
    card["text"] = render(card, main)
    return card


def render(card: dict, main: Optional[str] = None) -> str:
    """The card as text for the filing call, at most 1,500 characters."""
    lines = [f"{card['kind'].capitalize()}: {card['title']}"]
    if card.get("channel"):
        lines.append(f"Channel: {card['channel']}")
    if card.get("site"):
        lines.append(f"Site: {card['site']}")
    if card.get("published"):
        lines.append(f"Published: {card['published']}")
    facts = card.get("facts") or {}
    if facts.get("author"):
        lines.append(f"By: {facts['author']}")
    if facts.get("when"):
        lines.append(f"When: {facts['when']}" + (f" to {facts['ends']}" if facts.get("ends") else ""))
    if facts.get("where"):
        lines.append(f"Where: {facts['where']}")
    if facts.get("time"):
        lines.append(f"Time: {facts['time']}")
    if facts.get("yield"):
        lines.append(f"Makes: {facts['yield']}")
    if facts.get("duration"):
        lines.append(f"Length: {facts['duration']}")
    if facts.get("ingredients"):
        lines.append("Ingredients: " + "; ".join(facts["ingredients"]))
    if facts.get("steps"):
        lines.append("Steps: " + " ".join(f"{index}. {step}" for index, step in enumerate(facts["steps"], start=1)))
    if card.get("description"):
        lines.append(card["description"])
    if card.get("limited"):
        lines.append("Limited preview: only the title could be read.")
    text = "\n".join(lines)
    if main and not card.get("limited"):
        room = CARD_TEXT_LIMIT - len(text) - 1
        if room > 80:
            text = f"{text}\n{_clip(main, room)}"
    return _clip_block(text, CARD_TEXT_LIMIT)


def _clip_block(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


# --- the network (oEmbed); blocked in tests --------------------------------------------------


def _http_get(url: str, timeout: float = 6.0) -> bytes:
    import requests

    from app.capture.url_fetch import validate_public_http_url

    validate_public_http_url(url)
    response = requests.get(url, timeout=timeout, allow_redirects=False,
                            headers={"User-Agent": "LifeInboxCapture/1.0 (+local educational project)"})
    response.raise_for_status()
    return response.content[:200_000]


def fetch_oembed(url: str) -> Optional[dict]:
    """The video's exact title and channel from YouTube's or Vimeo's oEmbed; None
    for other sites or when it can't be read (the card then uses the page)."""
    target = oembed_url(url)
    if not target:
        return None
    try:
        data = json.loads(_http_get(target).decode("utf-8", errors="replace"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {key: _clip(data.get(key), 200) or None for key in ("title", "author_name", "provider_name")}
