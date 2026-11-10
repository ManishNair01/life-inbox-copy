import importlib
import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.auth_helpers import DEFAULT_TEST_PASSWORD, login, register


MODULES = (
    "app.main",
    "app.database",
    "app.auth",
    "app.config",
    "app.email_sender",
)


@pytest.fixture()
def app_modules(tmp_path, monkeypatch):
    test_db_path = tmp_path / "life_inbox_auth_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{test_db_path}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("LIFE_INBOX_ENV", raising=False)
    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "fake")
    for name in MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    assert database.engine.url.database == str(test_db_path)
    yield main, database
    database.engine.dispose()
    for name in MODULES:
        sys.modules.pop(name, None)


@pytest.fixture()
def client(app_modules):
    main, _ = app_modules
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def database(app_modules):
    return app_modules[1]


def session_cookie(client):
    return client.cookies.get("life_inbox_session")


# --- logged-out experience ------------------------------------------------


def test_logged_out_home_redirects_to_login(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"


def test_login_page_contains_no_app_markup(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Create New Life" in response.text
    assert "Enter your Life" in response.text
    assert "/static/login.css" in response.text
    assert "noteText" not in response.text
    assert "/static/app.js" not in response.text


def test_logged_out_api_calls_return_401(client):
    for path in ("/api/items", "/api/tasks", "/api/topics", "/api/auth/me"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"] == "Authentication required."


def test_every_private_api_route_requires_a_session(client, app_modules):
    """New routes are protected automatically; this fails if one is not."""
    main, _ = app_modules
    public = main.PUBLIC_PATHS
    checked = 0
    for route in main.app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api/") or path in public:
            continue
        concrete = path
        for param in getattr(route, "param_convertors", {}):
            concrete = concrete.replace("{" + param + "}", "1")
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            response = client.request(method, concrete)
            assert response.status_code == 401, f"{method} {path}"
            checked += 1
    assert checked > 30


def test_public_pages_load_without_session(client):
    for path in ("/privacy", "/terms", "/api/health", "/static/auth.js"):
        assert client.get(path).status_code == 200, path


# --- registration -----------------------------------------------------------


def test_register_creates_user_signs_in_and_hashes_password(client, database):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "  Alice@Example.COM ",
            "password": DEFAULT_TEST_PASSWORD,
            "display_name": "Alice",
            "confirm_adult": True,
            "accept_terms": True,
        },
    )
    assert response.status_code == 201
    user = response.json()
    assert user["email"] == "alice@example.com"
    assert user["display_name"] == "Alice"
    assert user["auth_provider"] == "password"
    assert "password_hash" not in user

    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    assert client.get("/api/auth/me").json()["id"] == user["id"]
    assert client.get("/", follow_redirects=False).status_code == 200

    creds = database.get_user_credentials_by_email("alice@example.com")
    assert creds["password_hash"].startswith("$argon2id$")
    assert DEFAULT_TEST_PASSWORD not in creds["password_hash"]
    with database.engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT adult_confirmed_at, terms_accepted_at FROM users "
                "WHERE id = :id"
            ),
            {"id": user["id"]},
        ).one()
    assert row.adult_confirmed_at and row.terms_accepted_at


def test_new_user_gets_own_default_topics(client):
    register(client, "topics@example.com")
    topics = client.get("/api/topics").json()
    assert len(topics) >= 9


@pytest.mark.parametrize(
    "overrides, status, fragment",
    [
        ({"password": "short1"}, 422, "at least 10"),
        ({"password": "password123"}, 422, "too common"),
        ({"password": "aaaaaaaaaaaa"}, 422, "too common"),
        ({"password": "bob@example.com"}, 422, "email"),
        ({"confirm_adult": False}, 422, "18"),
        ({"accept_terms": False}, 422, "Terms"),
        ({"email": "not-an-email"}, 422, "valid email"),
    ],
)
def test_register_rejects_invalid_input(client, overrides, status, fragment):
    payload = {
        "email": "bob@example.com",
        "password": DEFAULT_TEST_PASSWORD,
        "display_name": "Bob",
        "confirm_adult": True,
        "accept_terms": True,
        **overrides,
    }
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == status
    assert fragment.lower() in response.json()["detail"].lower()
    assert session_cookie(client) is None


def test_register_duplicate_email_is_rejected_case_insensitively(client):
    register(client, "dup@example.com")
    response = client.post(
        "/api/auth/register",
        json={
            "email": "DUP@example.com",
            "password": "another long passphrase",
            "confirm_adult": True,
            "accept_terms": True,
        },
    )
    assert response.status_code == 409


# --- login ------------------------------------------------------------------


def test_login_with_password(client):
    user = register(client, "carol@example.com")
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

    logged_in = login(client, "Carol@Example.com")
    assert logged_in["id"] == user["id"]
    assert client.get("/api/auth/me").json()["email"] == "carol@example.com"


def test_wrong_password_and_unknown_email_get_same_error(client):
    register(client, "dave@example.com")
    client.post("/api/auth/logout")

    wrong = client.post(
        "/api/auth/login",
        json={"email": "dave@example.com", "password": "not the password"},
    )
    unknown = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "not the password"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {
        "detail": "Incorrect email or password."
    }
    assert session_cookie(client) is None


def test_account_locks_after_repeated_failures(client, database):
    register(client, "erin@example.com")
    client.post("/api/auth/logout")
    for _ in range(5):
        response = client.post(
            "/api/auth/login",
            json={"email": "erin@example.com", "password": "wrong password!"},
        )
        assert response.status_code == 401

    locked = client.post(
        "/api/auth/login",
        json={"email": "erin@example.com", "password": DEFAULT_TEST_PASSWORD},
    )
    assert locked.status_code == 423

    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    with database.engine.begin() as connection:
        connection.execute(
            text("UPDATE users SET locked_until = :t WHERE email = :e"),
            {"t": past, "e": "erin@example.com"},
        )
    login(client, "erin@example.com")


def test_login_rotates_session_token(client):
    register(client, "frank@example.com")
    first = session_cookie(client)
    login(client, "frank@example.com")
    second = session_cookie(client)
    assert first and second and first != second

    client.cookies.clear()
    client.cookies.set("life_inbox_session", first)
    assert client.get("/api/auth/me").status_code == 401


def test_logged_in_user_visiting_login_is_sent_home(client):
    register(client, "gina@example.com")
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"


# --- logout -----------------------------------------------------------------


def test_logout_revokes_session_on_server(client):
    register(client, "hank@example.com")
    client.post("/api/items", json={"raw_text": "Hank private note"})
    token = session_cookie(client)

    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert session_cookie(client) is None
    assert client.get("/api/items").status_code == 401
    assert client.get("/", follow_redirects=False).status_code == 302

    # A copied token must not work after logout.
    client.cookies.set("life_inbox_session", token)
    assert client.get("/api/items").status_code == 401


def test_logout_without_session_is_harmless(client):
    assert client.post("/api/auth/logout").status_code == 200


def test_logout_all_signs_out_other_devices(client, app_modules):
    main, _ = app_modules
    register(client, "ivy@example.com")
    with TestClient(main.app) as other_device:
        login(other_device, "ivy@example.com")
        assert other_device.get("/api/auth/me").status_code == 200

        response = client.post("/api/auth/logout-all")
        assert response.json()["sessions_revoked"] == 2
        assert other_device.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me").status_code == 401


def test_idle_expired_session_is_rejected(client, database):
    register(client, "jack@example.com")
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with database.engine.begin() as connection:
        connection.execute(
            text("UPDATE auth_sessions SET idle_expires_at = :t"), {"t": past}
        )
    assert client.get("/api/auth/me").status_code == 401


def test_absolute_expired_session_is_rejected(client, database):
    register(client, "kate@example.com")
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with database.engine.begin() as connection:
        connection.execute(
            text("UPDATE auth_sessions SET absolute_expires_at = :t"), {"t": past}
        )
    assert client.get("/api/auth/me").status_code == 401


def test_garbage_session_cookie_is_rejected(client):
    client.cookies.set("life_inbox_session", "forged-token")
    assert client.get("/api/items").status_code == 401


# --- change password --------------------------------------------------------


def test_change_password_flow(client, app_modules):
    main, _ = app_modules
    register(client, "leo@example.com")
    new_password = "a brand new passphrase"

    wrong = client.post(
        "/api/auth/password/change",
        json={"current_password": "nope nope nope", "new_password": new_password},
    )
    assert wrong.status_code == 403

    weak = client.post(
        "/api/auth/password/change",
        json={"current_password": DEFAULT_TEST_PASSWORD, "new_password": "short"},
    )
    assert weak.status_code == 422

    same = client.post(
        "/api/auth/password/change",
        json={
            "current_password": DEFAULT_TEST_PASSWORD,
            "new_password": DEFAULT_TEST_PASSWORD,
        },
    )
    assert same.status_code == 422

    with TestClient(main.app) as other_device:
        login(other_device, "leo@example.com")
        changed = client.post(
            "/api/auth/password/change",
            json={
                "current_password": DEFAULT_TEST_PASSWORD,
                "new_password": new_password,
            },
        )
        assert changed.status_code == 200
        assert changed.json()["other_sessions_revoked"] == 1
        assert other_device.get("/api/auth/me").status_code == 401

    # Current session keeps working.
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/logout")
    old = client.post(
        "/api/auth/login",
        json={"email": "leo@example.com", "password": DEFAULT_TEST_PASSWORD},
    )
    assert old.status_code == 401
    login(client, "leo@example.com", password=new_password)


# --- isolation & hardening -------------------------------------------------


def test_users_only_see_their_own_content(client):
    alice = register(client, "alice-iso@example.com")
    note = client.post("/api/items", json={"raw_text": "Alice only"}).json()
    assert note["owner_user_id"] == alice["id"]
    client.post("/api/auth/logout")

    register(client, "bob-iso@example.com")
    assert client.get("/api/items").json() == []
    assert client.get(f"/api/items/{note['id']}").status_code == 404
    assert client.delete(f"/api/items/{note['id']}").status_code == 404
    client.post("/api/auth/logout")

    login(client, "alice-iso@example.com")
    items = client.get("/api/items").json()
    assert [item["id"] for item in items] == [note["id"]]


def test_cross_site_writes_are_blocked(client):
    register(client, "mia@example.com")
    blocked = client.post(
        "/api/items",
        json={"raw_text": "csrf attempt"},
        headers={"Origin": "https://evil.example"},
    )
    assert blocked.status_code == 403
    fetch_meta = client.post(
        "/api/items",
        json={"raw_text": "csrf attempt"},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert fetch_meta.status_code == 403
    same_origin = client.post(
        "/api/items",
        json={"raw_text": "legit"},
        headers={"Origin": "http://testserver"},
    )
    assert same_origin.status_code == 200
    assert [item["raw_text"] for item in client.get("/api/items").json()] == [
        "legit"
    ]


def test_security_headers_present(client):
    response = client.get("/login")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"
    api = client.get("/api/items")
    assert api.headers["cache-control"] == "no-store"
    # Scripts/styles must be revalidated so updates are never masked by cache.
    for asset in ("/static/auth.js", "/static/app.js", "/static/styles.css"):
        assert client.get(asset).headers["cache-control"] == "no-cache", asset


def test_require_owner_id_has_no_shared_fallback(database):
    database.set_current_owner_id(None)
    with pytest.raises(database.NotAuthenticatedError):
        database.require_owner_id()


# --- claiming legacy "Local Owner" data -------------------------------------


def test_claim_local_owner_moves_legacy_data_to_registered_account(
    client, database
):
    from datetime import datetime, timezone

    sys.modules.pop("scripts.claim_local_owner", None)
    claim_module = importlib.import_module("scripts.claim_local_owner")

    with database.engine.begin() as connection:
        local_id = connection.scalar(
            text("SELECT id FROM users WHERE email = :e"),
            {"e": database.DEFAULT_OWNER_EMAIL},
        )
        connection.execute(
            text(
                "INSERT INTO inbox_items (item_type, raw_text, processing_status,"
                " created_at, owner_user_id) VALUES ('text', 'Legacy note',"
                " 'ready', :now, :owner)"
            ),
            {"now": datetime.now(timezone.utc).isoformat(), "owner": local_id},
        )

    user = register(client, "claimer@example.com")
    assert client.get("/api/items").json() == []

    with pytest.raises(SystemExit):
        claim_module.claim("missing@example.com", dry_run=False)

    dry = claim_module.claim("claimer@example.com", dry_run=True)
    assert dry["status"] == "dry_run"
    assert dry["inbox_items"] == 1
    assert client.get("/api/items").json() == []

    result = claim_module.claim("Claimer@example.com", dry_run=False)
    assert result["status"] == "claimed"
    assert result["topics_merged"] >= 9
    items = client.get("/api/items").json()
    assert [item["raw_text"] for item in items] == ["Legacy note"]
    assert items[0]["owner_user_id"] == user["id"]
    assert database.get_user_by_email(database.DEFAULT_OWNER_EMAIL) is None

    again = claim_module.claim("claimer@example.com", dry_run=False)
    assert again["status"] == "nothing_to_claim"


# --- operator password reset -----------------------------------------------


def test_reset_password_script_sets_password_and_signs_out(client, database):
    sys.modules.pop("scripts.reset_password", None)
    reset = importlib.import_module("scripts.reset_password")

    # Account from the old dev login: exists, but has no password.
    database.ensure_user(
        email="legacy@example.com", display_name="Legacy", auth_provider="dev"
    )
    blocked = client.post(
        "/api/auth/login",
        json={"email": "legacy@example.com", "password": DEFAULT_TEST_PASSWORD},
    )
    assert blocked.status_code == 401

    with pytest.raises(reset.ResetError, match="at least 10"):
        reset.reset_password("legacy@example.com", "short")
    with pytest.raises(reset.ResetError, match="No account"):
        reset.reset_password("nobody@example.com", DEFAULT_TEST_PASSWORD)
    with pytest.raises(reset.ResetError, match="Local Owner"):
        reset.reset_password(database.DEFAULT_OWNER_EMAIL, DEFAULT_TEST_PASSWORD)

    result = reset.reset_password("Legacy@example.com", DEFAULT_TEST_PASSWORD)
    assert result["email"] == "legacy@example.com"
    login(client, "legacy@example.com")

    # A later reset signs out existing sessions and replaces the password.
    result = reset.reset_password("legacy@example.com", "a different passphrase")
    assert result["sessions_signed_out"] == 1
    assert client.get("/api/auth/me").status_code == 401
    login(client, "legacy@example.com", password="a different passphrase")


# --- forgot password (one-time code) ----------------------------------------

NEW_PASSWORD = "brand new reset passphrase"


def outbox():
    return sys.modules["app.email_sender"].FAKE_OUTBOX


def latest_code():
    import re

    message = [m for m in outbox() if "reset code" in m.subject][-1]
    return re.search(r"\b(\d{6})\b", message.body).group(1)


def request_code(client, email):
    response = client.post("/api/auth/password/forgot", json={"email": email})
    assert response.status_code == 202, response.text
    return response.json()


def reset(client, email, code, new_password=NEW_PASSWORD):
    return client.post(
        "/api/auth/password/reset",
        json={"email": email, "code": code, "new_password": new_password},
    )


def age_challenges(database, **delta):
    """Move every stored code into the past by the given timedelta."""
    shift = timedelta(**delta)
    with database.engine.begin() as connection:
        rows = connection.execute(
            text("SELECT id, created_at, expires_at FROM otp_challenges")
        ).all()
        for row in rows:
            connection.execute(
                text(
                    "UPDATE otp_challenges SET created_at = :c, expires_at = :e "
                    "WHERE id = :id"
                ),
                {
                    "c": (datetime.fromisoformat(row.created_at) - shift).isoformat(),
                    "e": (datetime.fromisoformat(row.expires_at) - shift).isoformat(),
                    "id": row.id,
                },
            )


def test_forgot_password_full_flow(client, app_modules, database):
    main, _ = app_modules
    register(client, "reset-me@example.com")
    with TestClient(main.app) as other_device:
        login(other_device, "reset-me@example.com")
        client.post("/api/auth/logout")

        sent = request_code(client, "Reset-Me@example.com")
        assert sent == {
            "status": "code_sent_if_account_exists",
            "resend_after_seconds": 60,
            "delivery": "fake",
        }
        assert outbox()[-1].to == "reset-me@example.com"
        code = latest_code()

        response = reset(client, "reset-me@example.com", f" {code[:3]} {code[3:]} ")
        assert response.status_code == 200, response.text
        assert response.json()["email"] == "reset-me@example.com"
        assert client.get("/api/auth/me").status_code == 200
        # Every other device is signed out.
        assert other_device.get("/api/auth/me").status_code == 401

    assert "password was changed" in outbox()[-1].subject
    client.post("/api/auth/logout")
    old = client.post(
        "/api/auth/login",
        json={"email": "reset-me@example.com", "password": DEFAULT_TEST_PASSWORD},
    )
    assert old.status_code == 401
    login(client, "reset-me@example.com", password=NEW_PASSWORD)

    # A code works only once.
    again = reset(client, "reset-me@example.com", code, "yet another passphrase")
    assert again.status_code == 400

    with database.engine.connect() as connection:
        stored = connection.execute(
            text("SELECT code_hash FROM otp_challenges")
        ).scalar_one()
    assert code not in stored


def test_forgot_password_does_not_reveal_unknown_emails(client):
    register(client, "known@example.com")
    client.post("/api/auth/logout")

    known = request_code(client, "known@example.com")
    sent_before = len(outbox())
    unknown = request_code(client, "unknown@example.com")
    assert known == unknown
    assert len(outbox()) == sent_before  # nothing emailed to unknown address

    wrong = "000000" if latest_code() != "000000" else "111111"
    wrong_known = reset(client, "known@example.com", wrong)
    wrong_unknown = reset(client, "unknown@example.com", wrong)
    assert wrong_known.status_code == wrong_unknown.status_code == 400
    assert wrong_known.json() == wrong_unknown.json()


def test_wrong_codes_are_limited(client):
    register(client, "guess@example.com")
    client.post("/api/auth/logout")
    request_code(client, "guess@example.com")
    code = latest_code()
    wrong = "111111" if code != "111111" else "222222"

    for left in (4, 3, 2, 1):
        response = reset(client, "guess@example.com", wrong)
        assert response.status_code == 400
        assert f"{left} attempt(s) left" in response.json()["detail"]
    fifth = reset(client, "guess@example.com", wrong)
    assert "Too many wrong codes" in fifth.json()["detail"]

    # Even the right code is now refused; a new code is required.
    blocked = reset(client, "guess@example.com", code)
    assert blocked.status_code == 400
    assert "Too many wrong codes" in blocked.json()["detail"]


def test_expired_code_is_rejected(client, database):
    register(client, "slow@example.com")
    client.post("/api/auth/logout")
    request_code(client, "slow@example.com")
    code = latest_code()
    age_challenges(database, minutes=11)
    response = reset(client, "slow@example.com", code)
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_new_code_replaces_old_one(client, database):
    register(client, "twice@example.com")
    client.post("/api/auth/logout")
    request_code(client, "twice@example.com")
    first = latest_code()
    age_challenges(database, seconds=61)  # past the resend cooldown
    request_code(client, "twice@example.com")
    second = latest_code()
    if first != second:
        assert reset(client, "twice@example.com", first).status_code == 400
    assert reset(client, "twice@example.com", second).status_code == 200


def test_code_requests_are_rate_limited(client, database):
    register(client, "spam@example.com")
    client.post("/api/auth/logout")
    request_code(client, "spam@example.com")
    too_soon = client.post(
        "/api/auth/password/forgot", json={"email": "spam@example.com"}
    )
    assert too_soon.status_code == 429
    assert "wait a minute" in too_soon.json()["detail"]

    for _ in range(4):
        age_challenges(database, seconds=61)
        request_code(client, "spam@example.com")
    age_challenges(database, seconds=61)
    sixth = client.post(
        "/api/auth/password/forgot", json={"email": "spam@example.com"}
    )
    assert sixth.status_code == 429
    assert "Too many codes" in sixth.json()["detail"]

    # Unknown emails are limited the same way, so a 429 reveals nothing.
    request_code(client, "ghost@example.com")
    ghost = client.post(
        "/api/auth/password/forgot", json={"email": "ghost@example.com"}
    )
    assert ghost.status_code == 429


def test_weak_new_password_does_not_use_up_the_code(client):
    register(client, "weak@example.com")
    client.post("/api/auth/logout")
    request_code(client, "weak@example.com")
    code = latest_code()
    weak = reset(client, "weak@example.com", code, "short")
    assert weak.status_code == 422
    assert reset(client, "weak@example.com", code).status_code == 200


def test_reset_unlocks_a_locked_account(client):
    register(client, "locked@example.com")
    client.post("/api/auth/logout")
    for _ in range(5):
        client.post(
            "/api/auth/login",
            json={"email": "locked@example.com", "password": "wrong password!"},
        )
    locked = client.post(
        "/api/auth/login",
        json={"email": "locked@example.com", "password": DEFAULT_TEST_PASSWORD},
    )
    assert locked.status_code == 423

    request_code(client, "locked@example.com")
    assert reset(client, "locked@example.com", latest_code()).status_code == 200
    client.post("/api/auth/logout")
    login(client, "locked@example.com", password=NEW_PASSWORD)


def test_console_email_and_local_pepper_rejected_outside_local(monkeypatch):
    sys.modules.pop("app.config", None)
    config = importlib.import_module("app.config")
    monkeypatch.setenv("LIFE_INBOX_ENV", "beta")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@db/x")
    monkeypatch.setenv("LIFE_INBOX_EMAIL_PROVIDER", "console")
    monkeypatch.delenv("LIFE_INBOX_OTP_PEPPER", raising=False)
    with pytest.raises(config.ConfigError) as error:
        config.load_config()
    assert "LIFE_INBOX_EMAIL_PROVIDER" in str(error.value)
    assert "LIFE_INBOX_OTP_PEPPER" in str(error.value)
    sys.modules.pop("app.config", None)
