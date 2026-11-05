"""Sign in with Google (OAuth 2.0 authorization-code flow with PKCE).

Flow: /api/auth/google/start sets a short-lived signed cookie holding the
state, nonce and PKCE verifier and redirects to Google; Google redirects back
to /auth/google/callback with a code, which the server exchanges directly with
Google's token endpoint (server to server, over TLS, using the client secret).

Because the id_token is received straight from Google's token endpoint over
TLS, its signature need not be re-verified (OpenID Connect Core 3.1.3.7); we
still validate issuer, audience, expiry, nonce and ``email_verified``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import requests

from app.config import AppConfig, load_config

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
VALID_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
STATE_COOKIE = "life_inbox_oauth"
STATE_TTL_SECONDS = 600


class GoogleAuthError(Exception):
    """Failure with a fixed code the login page maps to a friendly message."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(value: str) -> str:
    pepper = load_config(strict=False).otp_pepper.encode("utf-8")
    return _b64(hmac.new(pepper, value.encode("ascii"), hashlib.sha256).digest())


def pack_state(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def unpack_state(
    cookie: Optional[str], *, now: Optional[float] = None
) -> Optional[dict]:
    """Return the payload if the cookie is authentic and not expired."""
    if not cookie or "." not in cookie or len(cookie) > 2000:
        return None
    body, signature = cookie.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(body)):
        return None
    try:
        payload = json.loads(_unb64(body))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if (now if now is not None else time.time()) > payload.get("exp", 0):
        return None
    return payload


def begin(
    config: AppConfig, *, intent: str, adult: bool, terms: bool
) -> tuple[str, str]:
    """Return (signed cookie value, Google authorize URL)."""
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    cookie = pack_state(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "intent": intent,
            "adult": bool(adult),
            "terms": bool(terms),
            "exp": time.time() + STATE_TTL_SECONDS,
        }
    )
    query = urlencode(
        {
            "client_id": config.google_client_id,
            "redirect_uri": config.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    return cookie, f"{AUTH_URL}?{query}"


def _claims_from_id_token(id_token: str) -> dict:
    parts = id_token.split(".")
    if len(parts) != 3:
        raise GoogleAuthError("google_failed")
    try:
        claims = json.loads(_unb64(parts[1]))
    except (ValueError, UnicodeDecodeError):
        raise GoogleAuthError("google_failed")
    if not isinstance(claims, dict):
        raise GoogleAuthError("google_failed")
    return claims


def validate_claims(
    claims: dict, config: AppConfig, *, nonce: str, now: Optional[float] = None
) -> dict:
    """Check the id_token claims; return {sub, email, name}."""
    if claims.get("iss") not in VALID_ISSUERS:
        raise GoogleAuthError("google_failed")
    audience = claims.get("aud")
    if audience != config.google_client_id and not (
        isinstance(audience, list) and config.google_client_id in audience
    ):
        raise GoogleAuthError("google_failed")
    try:
        expires = float(claims.get("exp") or 0)
    except (TypeError, ValueError):
        raise GoogleAuthError("google_failed")
    if (now if now is not None else time.time()) >= expires:
        raise GoogleAuthError("google_failed")
    if not hmac.compare_digest(str(claims.get("nonce") or ""), nonce):
        raise GoogleAuthError("google_state")
    sub = str(claims.get("sub") or "")
    email = str(claims.get("email") or "").strip().lower()
    if not sub or not email:
        raise GoogleAuthError("google_failed")
    if claims.get("email_verified") not in (True, "true"):
        raise GoogleAuthError("google_unverified")
    return {"sub": sub, "email": email, "name": str(claims.get("name") or "")}


def exchange_code(
    config: AppConfig, *, code: str, verifier: str, nonce: str
) -> dict:
    """Swap the authorization code for tokens and validate the id_token."""
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret,
                "redirect_uri": config.google_redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": verifier,
            },
            timeout=10,
        )
    except requests.RequestException:
        raise GoogleAuthError("google_failed")
    if response.status_code != 200:
        raise GoogleAuthError("google_failed")
    try:
        id_token = response.json().get("id_token")
    except ValueError:
        raise GoogleAuthError("google_failed")
    if not isinstance(id_token, str):
        raise GoogleAuthError("google_failed")
    return validate_claims(_claims_from_id_token(id_token), config, nonce=nonce)
