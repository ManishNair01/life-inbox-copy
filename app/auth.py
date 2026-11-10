"""Password login with server-side sessions.

- Passwords are hashed with argon2id; plain passwords are never stored or logged.
- The session cookie holds a random token. Only its SHA-256 hash is stored in
  ``auth_sessions``, so logout revokes it immediately.
- Identity always comes from the session cookie, never from a browser-supplied
  user id.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Response

from app.config import load_config
from app.database import (
    EmailAlreadyRegisteredError,
    consume_otp_challenge,
    create_otp_challenge,
    create_auth_session,
    create_google_user,
    create_password_user,
    get_auth_session_by_token_hash,
    get_user_by_id,
    get_user_credentials_by_email,
    get_user_credentials_by_google_sub,
    get_user_credentials_by_id,
    link_google_to_user,
    list_recent_otp_challenges,
    record_login_success,
    record_otp_failure,
    record_password_failure,
    revoke_auth_session,
    revoke_user_auth_sessions,
    set_user_password_hash,
    touch_auth_session,
)
from app.email_sender import current_provider as current_email_provider
from app.email_sender import send_email


logger = logging.getLogger(__name__)

SESSION_COOKIE = "life_inbox_session"
SESSION_IDLE_TTL = timedelta(days=30)
SESSION_ABSOLUTE_TTL = timedelta(days=90)
SESSION_TOUCH_INTERVAL = timedelta(hours=1)

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128
LOCK_AFTER_FAILED_ATTEMPTS = 5
LOCK_DURATION = timedelta(minutes=15)

# Small built-in deny list; a larger breached-password list can replace it.
COMMON_PASSWORDS = frozenset(
    {
        "1234567890",
        "12345678910",
        "0123456789",
        "1111111111",
        "0000000000",
        "1q2w3e4r5t",
        "qwertyuiop",
        "asdfghjkl1",
        "password12",
        "password123",
        "password1234",
        "passw0rd123",
        "iloveyou123",
        "welcome123",
        "letmein123",
        "admin12345",
        "qwerty1234",
        "abcdefghij",
        "abc1234567",
        "lifeinbox1",
        "lifeinbox123",
    }
)

_hasher = PasswordHasher()
# Used to spend the same time on unknown emails as on real ones.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


class AuthError(Exception):
    """Auth failure with an HTTP status and a user-safe message."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


INVALID_CREDENTIALS = "Incorrect email or password."
PUBLIC_USER_FIELDS = ("id", "email", "display_name", "auth_provider", "created_at")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    cleaned = (email or "").strip().lower()
    local, _, domain = cleaned.partition("@")
    if (
        not local
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
        or len(cleaned) > 254
        or any(ch.isspace() for ch in cleaned)
    ):
        raise AuthError(422, "Enter a valid email address.")
    return cleaned


_SYMBOL = re.compile(r"[^A-Za-z0-9]")
_REPEAT = re.compile(r"(.)\1{3,}")


def _has_sequence(value: str, length: int = 4) -> bool:
    """True for a run like 1234, 9876, abcd or dcba (case-insensitive)."""
    lowered = value.lower()
    for start in range(len(lowered) - length + 1):
        chunk = lowered[start : start + length]
        if not (chunk.isalpha() or chunk.isdigit()):
            continue
        steps = {ord(b) - ord(a) for a, b in zip(chunk, chunk[1:])}
        if steps in ({1}, {-1}):
            return True
    return False


def password_problem(
    password: str, *, email: str = "", display_name: str = ""
) -> Optional[str]:
    """Return a user-facing reason the password is unacceptable, or None.

    Rules apply only when a password is *set* (register, reset, change);
    existing passwords are never re-checked at sign-in.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters."
    if len(password) > PASSWORD_MAX_LENGTH:
        return f"Password must be at most {PASSWORD_MAX_LENGTH} characters."
    if not password.strip():
        return "Password cannot be only spaces."
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) < 4:
        return "This password is too common. Choose something harder to guess."
    local = email.split("@", 1)[0].lower() if email else ""
    if email and (lowered == email.lower() or (len(local) >= 4 and lowered == local)):
        return "Password must not be your email address."

    missing = []
    if not any(ch.isupper() for ch in password):
        missing.append("an upper-case letter")
    if not any(ch.islower() for ch in password):
        missing.append("a lower-case letter")
    if not any(ch.isdigit() for ch in password):
        missing.append("a number")
    if not _SYMBOL.search(password):
        missing.append("a symbol (like ! or -)")
    if missing:
        return "Password needs " + ", ".join(missing) + "."

    if _REPEAT.search(password):
        return "Password must not repeat the same character 4 or more times in a row."
    if _has_sequence(password):
        return "Password must not contain an easy sequence like 1234 or abcd."
    if "lifeinbox" in lowered:
        return "Password must not contain the app name."
    if len(local) >= 4 and local in lowered:
        return "Password must not contain your email name."
    for word in re.split(r"\s+", (display_name or "").lower()):
        if len(word) >= 4 and word in lowered:
            return "Password must not contain your name."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _verify_password(password_hash: Optional[str], password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and bool(
            password_hash
        )
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# --- registration / login ---------------------------------------------------


def register_user(
    *,
    email: str,
    password: str,
    display_name: str,
    confirm_adult: bool,
    accept_terms: bool,
) -> dict:
    cleaned = normalize_email(email)
    if not confirm_adult:
        raise AuthError(422, "You must confirm you are 18 or older.")
    if not accept_terms:
        raise AuthError(422, "You must accept the Terms and Privacy Policy.")
    problem = password_problem(
        password, email=cleaned, display_name=display_name
    )
    if problem:
        raise AuthError(422, problem)
    try:
        return create_password_user(
            email=cleaned,
            display_name=(display_name or "").strip()[:100],
            password_hash=hash_password(password),
            now_iso=_iso(_now()),
        )
    except EmailAlreadyRegisteredError as exc:
        raise AuthError(
            409, "An account with this email already exists. Try signing in."
        ) from exc


def authenticate_password(email: str, password: str) -> dict:
    try:
        cleaned = normalize_email(email)
    except AuthError:
        raise AuthError(401, INVALID_CREDENTIALS)

    creds = get_user_credentials_by_email(cleaned)
    if creds is None or not creds["password_hash"]:
        _verify_password(None, password)  # equalize timing
        raise AuthError(401, INVALID_CREDENTIALS)

    now = _now()
    locked_until = _parse(creds["locked_until"])
    if locked_until and locked_until > now:
        _verify_password(None, password)
        raise AuthError(
            423,
            "Too many failed attempts. Try again in a few minutes.",
        )
    if creds["status"] != "active":
        _verify_password(None, password)
        raise AuthError(401, INVALID_CREDENTIALS)

    if not _verify_password(creds["password_hash"], password):
        record_password_failure(
            creds["id"],
            lock_after=LOCK_AFTER_FAILED_ATTEMPTS,
            locked_until_iso=_iso(now + LOCK_DURATION),
        )
        raise AuthError(401, INVALID_CREDENTIALS)

    if _hasher.check_needs_rehash(creds["password_hash"]):
        set_user_password_hash(creds["id"], hash_password(password), _iso(now))
    record_login_success(creds["id"], _iso(now))
    return get_user_by_id(creds["id"])


def change_password(
    user_id: int,
    *,
    current_password: str,
    new_password: str,
    keep_token: Optional[str],
) -> int:
    """Change the password and sign out every other session.

    Returns how many other sessions were revoked.
    """
    creds = get_user_credentials_by_id(user_id)
    if creds is None or not _verify_password(creds["password_hash"], current_password):
        raise AuthError(403, "Current password is incorrect.")
    problem = password_problem(
        new_password,
        email=creds["email"] or "",
        display_name=creds.get("display_name") or "",
    )
    if problem:
        raise AuthError(422, problem)
    if _verify_password(creds["password_hash"], new_password):
        raise AuthError(422, "New password must be different from the current one.")
    now_iso = _iso(_now())
    set_user_password_hash(user_id, hash_password(new_password), now_iso)
    return revoke_user_auth_sessions(
        user_id,
        now_iso=now_iso,
        reason="password_changed",
        keep_token_hash=hash_token(keep_token) if keep_token else None,
    )


def delete_account(user_id: int, *, password: str) -> dict:
    """Erase the account and everything in it (change 025). Your password,
    again, is the check."""
    from app.database import erase_user

    creds = get_user_credentials_by_id(user_id)
    if creds is None or not _verify_password(creds["password_hash"], password):
        raise AuthError(403, "That password isn't right, so nothing was deleted.")
    return erase_user(user_id)
# --- sign in with Google ----------------------------------------------------


class GoogleSignInError(Exception):
    """Failure with a fixed code the login page turns into a message."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sign_in_with_google(
    *,
    sub: str,
    email: str,
    display_name: str,
    intent: str,
    adult: bool,
    terms: bool,
) -> tuple[dict, str]:
    """Resolve a verified Google identity to a Life Inbox user.

    Returns (public user, outcome) where outcome is "existing", "linked" or
    "created". Linking an existing password account removes its password and
    signs out its other sessions, because sign-up does not verify email.
    """
    now_iso = _iso(_now())

    by_sub = get_user_credentials_by_google_sub(sub)
    if by_sub is not None:
        if by_sub["status"] != "active":
            raise GoogleSignInError("google_failed")
        record_login_success(by_sub["id"], now_iso)
        return {key: by_sub[key] for key in PUBLIC_USER_FIELDS}, "existing"

    try:
        cleaned = normalize_email(email)
    except AuthError:
        raise GoogleSignInError("google_failed")

    by_email = get_user_credentials_by_email(cleaned)
    if by_email is not None:
        if by_email["status"] != "active":
            raise GoogleSignInError("google_failed")
        link_google_to_user(by_email["id"], sub, now_iso)
        revoke_user_auth_sessions(
            by_email["id"], now_iso=now_iso, reason="google_linked"
        )
        record_login_success(by_email["id"], now_iso)
        return get_user_by_id(by_email["id"]), "linked"

    if intent != "register":
        raise GoogleSignInError("google_no_account")
    if not (adult and terms):
        raise GoogleSignInError("google_consent")
    user = create_google_user(
        email=cleaned,
        display_name=(display_name or "").strip()[:100],
        google_sub=sub,
        now_iso=now_iso,
    )
    record_login_success(user["id"], now_iso)
    return user, "created"


# --- forgot password (one-time code) ----------------------------------------

RESET_PURPOSE = "reset_password"
OTP_LENGTH = 6
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = timedelta(seconds=60)
OTP_MAX_PER_HOUR = 5
INVALID_CODE = "That code is invalid or has expired. Request a new code."


def _keyed_hash(value: str) -> str:
    pepper = load_config(strict=False).otp_pepper.encode("utf-8")
    return hmac.new(pepper, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _identifier_hash(email: str) -> str:
    return _keyed_hash(f"email:{email}")


def _hash_code(code: str) -> str:
    nonce = secrets.token_hex(8)
    return f"{nonce}:{_keyed_hash(f'{nonce}:{code}')}"


def _code_matches(code_hash: Optional[str], code: str) -> bool:
    if not code_hash or ":" not in code_hash:
        return False
    nonce, expected = code_hash.split(":", 1)
    return hmac.compare_digest(expected, _keyed_hash(f"{nonce}:{code}"))


def request_password_reset(email: str) -> dict:
    """Send a reset code if the email has an active account.

    The result is identical whether or not the account exists, so this
    endpoint can't be used to discover who has an account.
    """
    cleaned = normalize_email(email)
    if current_email_provider() == "off":
        raise AuthError(503, "Password reset by email isn't set up on this Life Inbox. "
                             "Ask the person who runs it to reset your password.")
    identifier = _identifier_hash(cleaned)
    now = _now()
    recent = list_recent_otp_challenges(
        purpose=RESET_PURPOSE,
        identifier_hash=identifier,
        since_iso=_iso(now - timedelta(hours=1)),
    )
    if recent and now - _parse(recent[0]["created_at"]) < OTP_RESEND_COOLDOWN:
        raise AuthError(429, "Please wait a minute before requesting another code.")
    if len(recent) >= OTP_MAX_PER_HOUR:
        raise AuthError(429, "Too many codes requested. Try again in an hour.")

    creds = get_user_credentials_by_email(cleaned)
    eligible = creds is not None and creds["status"] == "active"
    code = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}" if eligible else None
    create_otp_challenge(
        purpose=RESET_PURPOSE,
        identifier_hash=identifier,
        user_id=creds["id"] if eligible else None,
        code_hash=_hash_code(code) if code else None,
        now_iso=_iso(now),
        expires_iso=_iso(now + OTP_TTL),
        max_attempts=OTP_MAX_ATTEMPTS,
    )
    if code:
        minutes = int(OTP_TTL.total_seconds() // 60)
        try:
            send_email(
                cleaned,
                "Your Life Inbox password reset code",
                f"Your Life Inbox code is {code}.\n\n"
                f"It expires in {minutes} minutes and can be used once.\n"
                "If you didn't ask to reset your password, ignore this email; "
                "your password has not changed.",
            )
        except Exception:
            # Same response whether or not the account exists (and whether or
            # not mail works), so delivery problems must not leak as a 500.
            logger.exception("Could not send the password reset email")
    return {
        "resend_after_seconds": int(OTP_RESEND_COOLDOWN.total_seconds()),
        "delivery": current_email_provider(),
    }


def reset_password_with_code(email: str, code: str, new_password: str) -> dict:
    """Check the code, set the new password and sign out every session."""
    try:
        cleaned = normalize_email(email)
    except AuthError:
        raise AuthError(400, INVALID_CODE)
    problem = password_problem(new_password, email=cleaned)
    if problem:
        raise AuthError(422, problem)

    now = _now()
    recent = list_recent_otp_challenges(
        purpose=RESET_PURPOSE,
        identifier_hash=_identifier_hash(cleaned),
        since_iso=_iso(now - OTP_TTL),
    )
    # Only the newest code counts; requesting a new code retires older ones.
    challenge = recent[0] if recent else None
    if (
        challenge is None
        or challenge["consumed_at"] is not None
        or _parse(challenge["expires_at"]) <= now
    ):
        raise AuthError(400, INVALID_CODE)
    if challenge["attempts"] >= challenge["max_attempts"]:
        raise AuthError(400, "Too many wrong codes. Request a new code.")

    entered = "".join(ch for ch in (code or "") if not ch.isspace())
    if challenge["user_id"] is None or not _code_matches(
        challenge["code_hash"], entered
    ):
        record_otp_failure(challenge["id"])
        left = challenge["max_attempts"] - challenge["attempts"] - 1
        if left <= 0:
            raise AuthError(400, "Too many wrong codes. Request a new code.")
        raise AuthError(
            400, f"That code is not correct. {left} attempt(s) left."
        )

    if not consume_otp_challenge(challenge["id"], _iso(now)):
        raise AuthError(400, INVALID_CODE)
    creds = get_user_credentials_by_id(challenge["user_id"])
    if creds is None or creds["status"] != "active":
        raise AuthError(400, INVALID_CODE)

    now_iso = _iso(now)
    set_user_password_hash(creds["id"], hash_password(new_password), now_iso)
    revoke_user_auth_sessions(
        creds["id"], now_iso=now_iso, reason="password_reset"
    )
    send_email(
        cleaned,
        "Your Life Inbox password was changed",
        "Your Life Inbox password was just reset using a code sent to this "
        "email, and all devices were signed out.\n\n"
        "If this wasn't you, reset your password again right away.",
    )
    return {key: creds[key] for key in PUBLIC_USER_FIELDS}


# --- sessions ---------------------------------------------------------------


def start_session(
    user_id: int, *, auth_method: str, user_agent: Optional[str] = None
) -> str:
    """Create a new session and return the raw token for the cookie."""
    token = secrets.token_urlsafe(32)
    now = _now()
    create_auth_session(
        user_id=user_id,
        token_hash=hash_token(token),
        auth_method=auth_method,
        now_iso=_iso(now),
        idle_expires_iso=_iso(now + SESSION_IDLE_TTL),
        absolute_expires_iso=_iso(now + SESSION_ABSOLUTE_TTL),
        device_label=(user_agent or "")[:200] or None,
    )
    return token


def resolve_session(token: Optional[str]) -> Optional[dict]:
    """Return the signed-in user for a session token, or None."""
    if not token or len(token) > 200:
        return None
    record = get_auth_session_by_token_hash(hash_token(token))
    if record is None or record["revoked_at"] is not None:
        return None
    now = _now()
    if _parse(record["absolute_expires_at"]) <= now:
        return None
    if _parse(record["idle_expires_at"]) <= now:
        return None
    creds = get_user_credentials_by_id(record["user_id"])
    if creds is None or creds["status"] != "active":
        return None
    user = {key: creds[key] for key in PUBLIC_USER_FIELDS}
    last_seen = _parse(record["last_seen_at"])
    if last_seen is None or now - last_seen >= SESSION_TOUCH_INTERVAL:
        touch_auth_session(
            record["id"],
            now_iso=_iso(now),
            idle_expires_iso=_iso(now + SESSION_IDLE_TTL),
        )
    return user


def end_session(token: Optional[str]) -> None:
    if token:
        revoke_auth_session(hash_token(token), now_iso=_iso(_now()), reason="logout")


def end_all_sessions(user_id: int) -> int:
    return revoke_user_auth_sessions(
        user_id, now_iso=_iso(_now()), reason="logout_all"
    )


def _secure_cookies() -> bool:
    """HTTPS-only sign-in cookies: always in beta/production, and when you share
    your own PC's Life Inbox over an HTTPS tunnel (LIFE_INBOX_SECURE_COOKIES=1)."""
    if os.getenv("LIFE_INBOX_SECURE_COOKIES", "").strip() == "1":
        return True
    return os.getenv("LIFE_INBOX_ENV", "local") in {"beta", "production"}


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
        max_age=int(SESSION_ABSOLUTE_TTL.total_seconds()),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
    )
