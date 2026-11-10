"""Change 015: smart link capture. Saved test pages (a YouTube oEmbed reply, a
recipe, an article, an event, a page that gives almost nothing, a blocked
page) and duplicates reusing results. Tests never touch the real internet:
`fetch_url` is faked here and conftest blocks oEmbed requests."""

import importlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import register

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")
PROJECT_ROOT = Path(__file__).resolve().parent.parent

RECIPE_PAGE = """<!doctype html><html><head><title>Paneer tikka | Spice Kitchen</title>
<meta property="og:site_name" content="Spice Kitchen">
<meta name="description" content="Smoky paneer tikka in a home oven.">
<script type="application/ld+json">{"@context": "https://schema.org", "@type": "Recipe",
 "name": "Oven paneer tikka", "recipeIngredient": ["250 g paneer", "1 cup curd", "2 tsp tikka masala"],
 "recipeInstructions": [{"@type": "HowToStep", "text": "Mix the curd and spices."},
                        {"@type": "HowToStep", "text": "Marinate the paneer for an hour."},
                        {"@type": "HowToStep", "text": "Grill for 15 minutes."}],
 "totalTime": "PT1H30M", "recipeYield": "4 servings"}</script></head>
<body><nav>Home Recipes Shop Login</nav>
<div class="cookie-banner"><p>We use cookies. Accept all</div>
<main><h1>Oven paneer tikka</h1><p>My favourite weeknight dinner, ready in no time.</main>
<footer>Copyright Spice Kitchen. Privacy. Terms.</footer></body></html>"""

ARTICLE_PAGE = """<html><head><title>Rates held | Daily Ledger</title>
<script type="application/ld+json">{"@graph": [{"@type": "WebSite", "name": "Daily Ledger"},
 {"@type": "NewsArticle", "headline": "Central bank holds rates steady", "datePublished": "2026-11-05",
  "author": {"@type": "Person", "name": "A. Writer"}}]}</script></head>
<body><header><a>Subscribe now</a></header><div id="consent-popup">Allow tracking?</div>
<article><p>The central bank kept its key rate unchanged on Thursday, citing steady inflation and
growth that has slowed since the summer. Analysts had expected the pause, and markets barely moved.
The next meeting is in December, when new forecasts are due.</p></article>
<aside class="related">You may also like: ten other stories</aside></body></html>"""

EVENT_PAGE = """<html><head><title>Diwali Mela 2026</title>
<script type="application/ld+json">{"@type": "Event", "name": "Diwali Mela", "startDate": "2026-11-14T17:00",
 "location": {"@type": "Place", "name": "City Grounds"}}</script></head><body><p>Food, music and lights.</p></body></html>"""

THIN_PAGE = "<html><head><title>Loading…</title></head><body><div id='root'></div></body></html>"

OEMBED_REPLY = {"title": "Building agents with Nemotron", "author_name": "NVIDIA Developer",
                "provider_name": "YouTube", "thumbnail_url": "https://i.ytimg.com/vi/abc/hq.jpg", "html": "<iframe></iframe>"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'links.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
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


def serve(monkeypatch, pages, fetched=None, oembed=None):
    """fetch_url answers from `pages` {url: html or exception}; oEmbed from `oembed`."""
    main = sys.modules["app.main"]
    from app.capture import link_card
    from app.capture.url_fetch import extract_article

    def fake_fetch(url):
        if fetched is not None:
            fetched.append(url)
        page = pages[url]
        if isinstance(page, Exception):
            raise page
        return {"final_url": url, "status_code": 200, **extract_article(page, url), "html": page}

    monkeypatch.setattr(main, "fetch_url", fake_fetch)
    # No DNS either: the address check (tested in test_api) would look the host up.
    monkeypatch.setattr(main, "validate_public_http_url", lambda url: url.strip())
    if oembed is not None:
        monkeypatch.setattr(link_card, "_http_get", lambda url, timeout=6.0: json.dumps(oembed).encode())


def save_link(client, url, context=None):
    response = client.post("/api/items/url", json={"url": url, **({"context": context} if context else {})})
    assert response.status_code in (200, 201), response.text
    return response.json()


# --- tidy links -----------------------------------------------------------------------------


def test_links_are_tidied():
    from app.capture.link_card import tidy_url

    assert tidy_url("https://Example.com/post/?utm_source=x&utm_medium=y&id=7#comments") == "https://example.com/post?id=7"
    assert tidy_url("https://youtu.be/abc123?si=TRACK&t=42") == "https://www.youtube.com/watch?v=abc123&t=42"
    assert tidy_url("https://m.youtube.com/watch?v=abc123&feature=share") == "https://www.youtube.com/watch?v=abc123"
    assert tidy_url("https://shop.example.com/item?fbclid=1&gclid=2&colour=red") == "https://shop.example.com/item?colour=red"


# --- the card: free facts before any AI ---------------------------------------------------------


def test_a_youtube_link_gets_its_exact_title_and_channel(client, monkeypatch):
    url = "https://www.youtube.com/watch?v=abc123"
    serve(monkeypatch, {url: "<html><head><title>- YouTube</title></head><body></body></html>"}, oembed=OEMBED_REPLY)
    item = save_link(client, "https://youtu.be/abc123?si=SHARE")
    assert item["source_url"] == url  # stored tidy
    card = item["link_card"]
    assert card["kind"] == "video" and card["title"] == "Building agents with Nemotron"
    assert card["channel"] == "NVIDIA Developer" and card["site"] == "YouTube"
    assert item["title"] == "Building agents with Nemotron"
    # Text only (decision I): no thumbnail or player is kept.
    assert "thumbnail" not in json.dumps(card) and "iframe" not in json.dumps(card)
    assert "Channel: NVIDIA Developer" in card["text"]


def test_a_recipe_page_gives_its_ingredients_and_steps(client, monkeypatch):
    url = "https://spice.example.com/paneer-tikka"
    serve(monkeypatch, {url: RECIPE_PAGE})
    card = save_link(client, url)["link_card"]
    assert card["kind"] == "recipe" and card["title"] == "Oven paneer tikka" and card["site"] == "Spice Kitchen"
    assert card["facts"]["ingredients"] == ["250 g paneer", "1 cup curd", "2 tsp tikka masala"]
    assert card["facts"]["steps"][0] == "Mix the curd and spices." and len(card["facts"]["steps"]) == 3
    assert "Ingredients: 250 g paneer; 1 cup curd" in card["text"]
    assert card["facts"]["time"] == "1 h 30 min" and card["facts"]["yield"] == "4 servings"
    # Menus, cookie banners and footers are left out; the main text (after an
    # unclosed <p> in the banner) is still read.
    for noise in ("Login", "cookies", "Copyright"):
        assert noise not in card["text"]
    assert "weeknight dinner" in card["text"]


def test_an_article_gives_its_headline_date_and_author(client, monkeypatch):
    url = "https://ledger.example.com/rates"
    serve(monkeypatch, {url: ARTICLE_PAGE})
    card = save_link(client, url)["link_card"]
    assert card["kind"] == "article" and card["title"] == "Central bank holds rates steady"
    assert card["published"] == "2026-11-05" and card["facts"]["author"] == "A. Writer"
    assert "kept its key rate unchanged" in card["text"]
    for noise in ("Subscribe now", "Allow tracking", "You may also like"):
        assert noise not in card["text"]
    assert card["limited"] is False


def test_an_event_page_gives_its_date_and_place(client, monkeypatch):
    url = "https://events.example.com/mela"
    serve(monkeypatch, {url: EVENT_PAGE})
    card = save_link(client, url)["link_card"]
    assert card["kind"] == "event" and card["facts"]["when"] == "2026-11-14T17:00"
    assert card["facts"]["where"] == "City Grounds"
    assert "When: 2026-11-14T17:00" in card["text"] and "Where: City Grounds" in card["text"]


def test_a_page_that_gives_almost_nothing_says_so(client, monkeypatch):
    url = "https://app.example.com/thing"
    serve(monkeypatch, {url: THIN_PAGE})
    card = save_link(client, url)["link_card"]
    assert card["limited"] is True
    assert "Limited preview: only the title could be read." in card["text"]


def test_a_blocked_page_is_a_capture_that_couldnt_be_read(client, monkeypatch):
    url = "https://members.example.com/private"
    serve(monkeypatch, {url: ValueError("Upstream returned HTTP 403")})
    item = save_link(client, url)
    assert item["processing_status"] == "failed" and item["link_card"] is None
    cards = client.get("/api/captain/needs-you").json()["cards"]
    assert any(c["kind"] == "failed" and c["item_id"] == item["id"] for c in cards)


def test_the_card_is_short_and_is_what_filing_sees(client, monkeypatch):
    url = "https://ledger.example.com/long"
    long_page = ARTICLE_PAGE.replace("The next meeting", "Lots more words here. " * 400 + "The next meeting")
    serve(monkeypatch, {url: long_page})
    item = save_link(client, url, context="for my economics class")
    assert len(item["link_card"]["text"]) <= 1500
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    try:
        note = database.get_note_from_db(item["id"])
    finally:
        database.set_current_owner_id(None)
    # The filing call's source for a link is its card, apart from your words.
    assert note["text"] == item["link_card"]["text"] and note["context"] == "for my economics class"


# --- a link saved twice reuses its earlier result ---------------------------------------------


def test_a_link_saved_again_reuses_its_result_without_fetching(client, monkeypatch):
    url = "https://spice.example.com/paneer-tikka"
    fetched = []
    serve(monkeypatch, {url: RECIPE_PAGE}, fetched=fetched)
    first = save_link(client, url)
    assert client.post("/api/analyze", params={"item_id": first["id"]}).status_code == 200
    again = save_link(client, "https://spice.example.com/paneer-tikka/?utm_source=whatsapp")
    assert fetched == [url]  # read once
    assert again["reused_from"] == first["id"] and again["filing_reused"] is True
    assert again["link_card"] == first["link_card"] and again["processing_status"] == "ready"
    # Filed like the first one, without an AI call.
    first_filing = client.get(f"/api/items/{first['id']}/insight").json()
    again_filing = client.get(f"/api/items/{again['id']}/insight").json()
    assert again_filing["effective_topic_id"] == first_filing["effective_topic_id"]
    assert "same link" in again_filing["rationale"]


def test_a_link_saved_again_with_a_new_note_is_filed_again(client, monkeypatch):
    url = "https://spice.example.com/paneer-tikka"
    serve(monkeypatch, {url: RECIPE_PAGE})
    first = save_link(client, url)
    client.post("/api/analyze", params={"item_id": first["id"]})
    again = save_link(client, url, context="cook this for my date on Saturday")
    # The page isn't read again, but your new words can change where it goes (R3).
    assert again["reused_from"] == first["id"] and again["filing_reused"] is False
    assert client.get(f"/api/items/{again['id']}/insight").status_code == 404  # not filed yet
    client.post("/api/analyze", params={"item_id": again["id"]})
    topics = {t["id"]: t["name"] for t in client.get("/api/topics").json()}
    assert topics[client.get(f"/api/items/{again['id']}/insight").json()["effective_topic_id"]] == "Occasions & gifts"


def test_links_are_never_shared_between_accounts(client, monkeypatch):
    url = "https://spice.example.com/paneer-tikka"
    fetched = []
    serve(monkeypatch, {url: RECIPE_PAGE}, fetched=fetched)
    save_link(client, url)
    client.post("/api/auth/logout")
    register(client, "other@example.com")
    theirs = save_link(client, url)
    assert theirs["reused_from"] is None and fetched == [url, url]


# --- migration 0024 ------------------------------------------------------------------------


def test_migration_0024_adds_the_link_card(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'v23.db'}")
    command.upgrade(config, "0023_filing_v2")
    command.upgrade(config, "0024_link_cards")
    engine = create_engine(f"sqlite:///{tmp_path / 'v23.db'}")
    try:
        assert "link_card" in {c["name"] for c in inspect(engine).get_columns("inbox_items")}
    finally:
        engine.dispose()
