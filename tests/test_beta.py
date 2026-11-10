"""Changes 024 and 025: "Create New Life" onboarding, the AI switch (decision
Q) and deleting your account. The AI is always faked."""

import importlib
import json
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.auth_helpers import DEFAULT_TEST_PASSWORD, login, register
from tests.test_filing import entry, notes_in

MODULES = ("app.main", "app.database", "app.auth", "app.config", "app.organizer")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'beta.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    monkeypatch.setattr(importlib.import_module("app.llm"), "RETRY_DELAY_SECONDS", 0)
    with TestClient(main.app) as test_client:
        yield test_client
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


def sign_up(client, email="owner@example.com", **extra):
    response = client.post("/api/auth/register", json={
        "email": email, "password": DEFAULT_TEST_PASSWORD, "display_name": "", "confirm_adult": True,
        "accept_terms": True, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def fake_ai(monkeypatch, prompts):
    import openai

    def create(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        prompts.append(prompt)
        answer = {"notes": [entry(n["id"], "Study", "learn") for n in notes_in(prompt)]} if "Notes (JSON):" in prompt else {}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))])

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(openai, "OpenAI", lambda **_kwargs: fake)
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")


# --- 024: onboarding --------------------------------------------------------------------------------


def test_a_new_account_is_asked_and_answers_become_core_facts(client):
    sign_up(client)
    state = client.get("/api/onboarding").json()
    assert state["show"] is True and state["done"] is False and "cooking" in state["focus"]
    result = client.post("/api/onboarding", json={
        "role": "student", "city": "Lucknow", "focus": ["studies", "cooking", "travel"],
        "care": "my parents' medicines", "health_memory_consent": True}).json()
    texts = {fact["text"]: fact for fact in result["facts"]}
    assert set(texts) == {"You are a student", "You live in Lucknow",
                          "Your days are mostly about College and studies, Cooking and Travel",
                          "You look after my parents' medicines"}
    assert all(f["core_profile"] and f["status"] == "confirmed" and f["source_kind"] == "onboarding" for f in texts.values())
    assert texts["You look after my parents' medicines"]["bot_key"] == "health"  # medical words need the consent given
    assert client.get("/api/settings").json()["health_memory_consent"] is True
    assert client.get("/api/onboarding").json()["show"] is False


def test_without_health_consent_a_medical_answer_isnt_kept(client):
    sign_up(client)
    result = client.post("/api/onboarding", json={"role": "working", "care": "my father's diabetes"}).json()
    assert [f["text"] for f in result["facts"]] == ["You work"]


def test_skipping_works_and_filing_still_works_with_no_memory(client, monkeypatch):
    sign_up(client)
    assert client.post("/api/onboarding/skip").json() == {"status": "skipped"}
    assert client.get("/api/onboarding").json()["show"] is False
    note = client.post("/api/items", json={"raw_text": "Revise statistics before the quiz"}).json()
    assert client.post("/api/analyze", params={"item_id": note["id"]}).status_code == 200


def test_an_existing_account_with_notes_isnt_asked(client):
    sign_up(client)
    client.post("/api/items", json={"raw_text": "An old note"})
    assert client.get("/api/onboarding").json()["show"] is False
    assert client.post("/api/onboarding", json={"focus": ["not-a-choice"]}).status_code == 200  # unknown choices ignored
    assert client.post("/api/onboarding", json={"bogus": 1}).status_code == 422


# --- 025: the AI switch (decision Q) -------------------------------------------------------------------


def test_sign_up_unticked_means_ai_off_and_nothing_is_sent(client, monkeypatch):
    prompts = []
    fake_ai(monkeypatch, prompts)
    sign_up(client, ai_processing=False)
    assert client.get("/api/settings").json()["ai_processing"] is False
    note = client.post("/api/items", json={"raw_text": "Revise statistics before the quiz"}).json()
    client.post("/api/analyze", params={"item_id": note["id"]})
    client.post("/api/ask", json={"question": "What should I revise?"})
    assert prompts == []  # one switch: no AI call at all
    insight = client.get(f"/api/items/{note['id']}/insight").json()
    assert insight["filed_by"] == "offline"


def test_the_switch_in_settings_turns_ai_on_and_off(client, monkeypatch):
    prompts = []
    fake_ai(monkeypatch, prompts)
    sign_up(client, ai_processing=True)
    first = client.post("/api/items", json={"raw_text": "Revise statistics before the quiz"}).json()
    client.post("/api/analyze", params={"item_id": first["id"]})
    assert len(prompts) == 1
    client.patch("/api/settings", json={"ai_processing": False})
    second = client.post("/api/items", json={"raw_text": "Revise probability too"}).json()
    client.post("/api/analyze", params={"item_id": second["id"]})
    assert len(prompts) == 1


def test_older_clients_and_existing_accounts_keep_ai_on(client):
    sign_up(client)  # no ai_processing field
    assert client.get("/api/settings").json()["ai_processing"] is True


def test_the_gateway_itself_refuses_when_the_switch_is_off(client, monkeypatch):
    from app import llm

    sign_up(client, ai_processing=False)
    database = sys.modules["app.database"]
    me = client.get("/api/auth/me").json()
    database.set_current_owner_id((me.get("user") or me)["id"])
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test-only")
    try:
        assert llm.is_configured() is False
        with pytest.raises(llm.AiSwitchedOff):
            llm.complete_text("filing", "hello")
    finally:
        database.set_current_owner_id(None)


def test_the_sign_up_page_asks_with_the_box_unticked(client):
    page = client.get("/login").text
    assert 'id="registerAi" type="checkbox" />' in page  # not "checked"
    assert "nothing is sent to an AI" in page


# --- 025: deleting your account ---------------------------------------------------------------------


def test_deleting_your_account_erases_only_yours(client, tmp_path):
    from tests.pdf_fixtures import make_text_pdf

    sign_up(client, "keep@example.com")
    kept = client.post("/api/items", json={"raw_text": "Someone else's note"}).json()
    client.post("/api/auth/logout")

    sign_up(client, "leave@example.com")
    note = client.post("/api/items", json={"raw_text": "Pay the hostel fees by Friday"}).json()
    client.post("/api/analyze", params={"item_id": note["id"]})
    pdf = client.post("/api/items/pdf", files={"file": ("a.pdf", make_text_pdf(), "application/pdf")}).json()
    client.post("/api/tasks", json={"text": "Call the warden"})
    client.post("/api/onboarding", json={"city": "Pune"})
    stored = list((tmp_path / "uploads").rglob("*"))
    assert any(path.is_file() for path in stored)

    assert client.post("/api/auth/account/delete", json={"password": "wrong password!", "confirm": "DELETE"}).status_code == 403
    assert client.post("/api/auth/account/delete", json={"password": DEFAULT_TEST_PASSWORD, "confirm": "delete"}).status_code == 422
    assert client.get(f"/api/items/{note['id']}").status_code == 200  # nothing deleted yet

    response = client.post("/api/auth/account/delete", json={"password": DEFAULT_TEST_PASSWORD, "confirm": "DELETE"})
    assert response.status_code == 200, response.text
    removed = response.json()["removed"]
    assert removed["users"] == 1 and removed["inbox_items"] == 2 and removed["files"] == 1
    assert client.get("/api/items").status_code == 401  # signed out
    assert client.post("/api/auth/login", json={"email": "leave@example.com", "password": DEFAULT_TEST_PASSWORD}).status_code == 401
    assert not any(path.is_file() and pdf["storage_path"].split("/")[-1] in path.name for path in (tmp_path / "uploads").rglob("*"))

    login(client, "keep@example.com")
    assert [item["id"] for item in client.get("/api/items").json()] == [kept["id"]]


def test_the_privacy_page_covers_the_beta(client):
    text = client.get("/privacy").text
    for needed in ("Delete my account", "AI processing", "switch", "DPDP", "GDPR", "Health memory",
                   "Weekly review", "Captain's greeting", "export"):
        assert needed in text, needed
    terms = client.get("/terms").text
    assert "Delete my account" in terms
