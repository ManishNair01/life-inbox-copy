"""Sign in with Google: full server-side flow with Google's token endpoint mocked."""

import base64
import json
import sys
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from tests.auth_helpers import DEFAULT_TEST_PASSWORD
from tests.test_calendar import client  # noqa: F401  (shared fixture)

CLIENT_ID = "test-client.apps.googleusercontent.com"


@pytest.fixture()
def google(client, monkeypatch):  # noqa: F811
    """Google configured; the fixture's owner user is signed out first."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    client.post("/api/auth/logout")
    client.cookies.clear()
    return client


def _b64(data: dict) -> str:
    raw = json.dumps(data).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _id_token(expected_nonce, **overrides):
    claims = {
        "iss": "https://accounts.google.com",
        "aud": CLIENT_ID,
        "exp": time.time() + 600,
        "nonce": expected_nonce,
        "sub": "google-sub-1",
        "email": "newbie@example.com",
        "email_verified": True,
        "name": "New Bie",
        **overrides,
    }
    return f"{_b64({'alg': 'RS256'})}.{_b64(claims)}.sig"


def _start(client, intent="signin", adult=False, terms=False):
    params = {"intent": intent}
    if adult:
        params["adult"] = "1"
    if terms:
        params["terms"] = "1"
    response = client.get(
        "/api/auth/google/start", params=params, follow_redirects=False
    )
    assert response.status_code == 302, response.text
    location = response.headers["location"]
    if not location.startswith("https://accounts.google.com/"):
        return location, None
    query = parse_qs(urlparse(location).query)
    return location, {key: value[0] for key, value in query.items()}


def _mock_token_endpoint(monkeypatch, *, status=200, **claim_overrides):
    calls = []

    def fake_post(url, data=None, timeout=None):
        calls.append(data)
        token = _id_token(fake_post.nonce, **claim_overrides)
        return SimpleNamespace(
            status_code=status, json=lambda: {"id_token": token}
        )

    fake_post.nonce = None
    fake_post.calls = calls
    monkeypatch.setattr("app.google_auth.requests.post", fake_post)
    return fake_post


def _login_via_google(client, monkeypatch, *, intent="register", adult=True,
                      terms=True, status=200, state_override=None, **claims):
    location, params = _start(client, intent, adult, terms)
    assert params is not None, location
    fake = _mock_token_endpoint(monkeypatch, status=status, **claims)
    fake.nonce = params["nonce"]
    response = client.get(
        "/auth/google/callback",
        params={"code": "auth-code", "state": state_override or params["state"]},
        follow_redirects=False,
    )
    return response, fake, params


def _database():
    return sys.modules["app.database"]


def test_providers_reflect_configuration(client, monkeypatch):  # noqa: F811
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
    assert client.get("/api/auth/providers").json() == {"google": False}
    assert client.get("/api/auth/google/start", follow_redirects=False).status_code == 404
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s")
    assert client.get("/api/auth/providers").json() == {"google": True}


def test_start_redirects_to_google_with_pkce_and_state(google):
    location, params = _start(google, "register", adult=True, terms=True)
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert params["client_id"] == CLIENT_ID
    assert params["response_type"] == "code"
    assert params["code_challenge_method"] == "S256"
    assert params["scope"] == "openid email profile"
    assert params["state"] and params["nonce"] and params["code_challenge"]
    assert "life_inbox_oauth" in google.cookies


def test_register_requires_both_consent_boxes(google):
    location, params = _start(google, "register", adult=True, terms=False)
    assert params is None
    assert location == "/login?error=google_consent&tab=register"


def test_new_user_created_with_google(google, monkeypatch):
    response, fake, _ = _login_via_google(google, monkeypatch)
    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert fake.calls[0]["grant_type"] == "authorization_code"
    assert fake.calls[0]["code_verifier"]

    me = google.get("/api/auth/me").json()
    assert me["email"] == "newbie@example.com"
    assert me["display_name"] == "New Bie"
    assert me["auth_provider"] == "google"
    assert len(google.get("/api/topics").json()) >= 9

    creds = _database().get_user_credentials_by_email("newbie@example.com")
    assert creds["password_hash"] is None
    assert creds["status"] == "active"


def test_signin_with_unknown_email_does_not_create_account(google, monkeypatch):
    response, _, _ = _login_via_google(google, monkeypatch, intent="signin",
                                       adult=False, terms=False)
    assert response.headers["location"] == "/login?error=google_no_account"
    assert _database().get_user_credentials_by_email("newbie@example.com") is None
    assert google.get("/api/auth/me").status_code == 401


def test_returning_user_signs_in_by_google_sub(google, monkeypatch):
    _login_via_google(google, monkeypatch)
    google.post("/api/auth/logout")
    google.cookies.clear()
    # Same Google account, even if the email claim changed.
    response, _, _ = _login_via_google(
        google, monkeypatch, intent="signin", adult=False, terms=False,
        email="renamed@example.com",
    )
    assert response.headers["location"] == "/"
    assert google.get("/api/auth/me").json()["email"] == "newbie@example.com"


@pytest.mark.parametrize(
    "overrides, code",
    [
        ({"aud": "someone-else"}, "google_failed"),
        ({"iss": "https://evil.example"}, "google_failed"),
        ({"exp": 1}, "google_failed"),
        ({"nonce": "wrong"}, "google_state"),
        ({"email_verified": False}, "google_unverified"),
        ({"email": ""}, "google_failed"),
    ],
)
def test_bad_id_token_claims_are_rejected(google, monkeypatch, overrides, code):
    response, _, _ = _login_via_google(google, monkeypatch, **overrides)
    assert response.headers["location"].startswith(f"/login?error={code}")
    assert google.get("/api/auth/me").status_code == 401
    assert _database().get_user_credentials_by_email("newbie@example.com") is None


def test_token_endpoint_failure_is_rejected(google, monkeypatch):
    response, _, _ = _login_via_google(google, monkeypatch, status=400)
    assert response.headers["location"].startswith("/login?error=google_failed")
    assert google.get("/api/auth/me").status_code == 401


def test_state_mismatch_missing_and_expired_cookie(google, monkeypatch):
    response, _, _ = _login_via_google(google, monkeypatch, state_override="forged")
    assert response.headers["location"].startswith("/login?error=google_state")

    google.cookies.clear()
    missing = google.get(
        "/auth/google/callback",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert missing.headers["location"].startswith("/login?error=google_state")

    from app import google_auth

    expired = google_auth.pack_state(
        {"state": "s", "nonce": "n", "verifier": "v", "intent": "register",
         "adult": True, "terms": True, "exp": time.time() - 5}
    )
    google.cookies.set("life_inbox_oauth", expired)
    late = google.get(
        "/auth/google/callback",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert late.headers["location"].startswith("/login?error=google_state")

    google.cookies.set("life_inbox_oauth", expired[:-3] + "abc")
    forged = google.get(
        "/auth/google/callback",
        params={"code": "c", "state": "s"},
        follow_redirects=False,
    )
    assert forged.headers["location"].startswith("/login?error=google_state")


def test_google_denied_by_user(google):
    _start(google, "signin")
    response = google.get(
        "/auth/google/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert response.headers["location"].startswith("/login?error=google_denied")


def test_linking_existing_password_account_removes_password_and_sessions(
    client, monkeypatch  # noqa: F811
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    # The fixture's owner@example.com is signed in with a password session.
    old_token = client.cookies.get("life_inbox_session")
    assert old_token
    client.cookies.clear()

    response, _, _ = _login_via_google(
        client, monkeypatch, intent="signin", adult=False, terms=False,
        email="owner@example.com", sub="google-owner",
    )
    assert response.headers["location"] == "/?google=linked"
    assert client.get("/api/auth/me").json()["email"] == "owner@example.com"

    creds = _database().get_user_credentials_by_email("owner@example.com")
    assert creds["password_hash"] is None

    # The earlier password session is dead and the old password no longer works.
    client.cookies.clear()
    client.cookies.set("life_inbox_session", old_token)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.clear()
    bad = client.post(
        "/api/auth/login",
        json={"email": "owner@example.com", "password": DEFAULT_TEST_PASSWORD},
    )
    assert bad.status_code == 401


def test_google_only_account_cannot_use_password_login(google, monkeypatch):
    _login_via_google(google, monkeypatch)
    google.post("/api/auth/logout")
    google.cookies.clear()
    response = google.post(
        "/api/auth/login",
        json={"email": "newbie@example.com", "password": DEFAULT_TEST_PASSWORD},
    )
    assert response.status_code == 401
