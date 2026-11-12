"""Secrets in notes (change 016, decision J).

A note that looks like it holds a secret (a password, PIN, OTP, card number,
bank account, Aadhaar or PAN number, Wi-Fi key, API key or token) is:
- hidden on screen until you tap "Show";
- never sent to the AI (it's filed by the offline matcher, from a masked copy);
- never turned into memory.

Detection is by pattern, on purpose cautious: a false alarm only hides a note
until you tap it. `mask_secrets` keeps the label and hides the value
("Wifi password: ••••").
"""

from __future__ import annotations

import re

MASK = "••••"

# "PIN code" is a postal code in India; bare "pass", "token" and "secret"
# ("boarding pass", "token number 45", "secret santa") aren't secrets.
_LABEL = (
    r"\b(?:password|passcode|passwd|pwd|pin(?!\s*code)|m-?pin|upi pin|otp|cvv|cvc|security code|"
    r"wi-?fi (?:password|key|pass)|wpa key|api[_ -]?key|secret key|access token|auth token|api token|"
    r"bearer token|recovery code|backup code)\b"
)
# Small words are never the secret: "Password for oracle is X" hides X, not "for".
_NOT_A_VALUE = r"(?:for|of|to|on|at|in|the|my|a|an|is|was|will|and|or|with|from)\b"
# A label, then its value ("password: hunter2", "PIN 4821", "otp is 662211"), maybe
# with who it's for in between ("password for oracle is X", "wifi password at home - X").
_LABELLED = re.compile(
    rf"(?P<label>{_LABEL})"
    r"(?P<sep>"
    r"\s+(?:for|of|to|on|at|in)(?:\s+[^\s,;:=•]+){1,4}?\s*(?:\s(?:is|was)\b|=|:|\s-)\s*"
    r"|\s*(?:\b(?:is|was)\b|=|:|-)\s*"
    # No "is" or ":": the next word counts only if it has a digit or symbol
    # ("PIN 4821", "password hunter2"), not "password before the 15th".
    r"|\s+(?=[^\s,;]*[\d@#$%^&*!?_+~])"
    rf")(?P<value>(?!•)(?!{_NOT_A_VALUE})[^\s,;]{{3,}})",
    re.I,
)
# Safety net: in a sentence that names a secret, a password-like word (letters
# with digits or symbols, 6+ long) is hidden even when the value isn't placed.
_LABEL_ONLY = re.compile(_LABEL, re.I)
_SENTENCE = re.compile(r"[^.!?\n]+[.!?\n]*")
_PASSWORDY = re.compile(
    r"(?<![^\s(\"'])(?=[^\s,;]*[A-Za-z])(?=[^\s,;]*[\d@#$%^&*!?+~])(?!•)[^\s,;]{6,}"
)


def _passwordy(text: str) -> list[re.Match]:
    found = []
    for sentence in _SENTENCE.finditer(text or ""):
        if _LABEL_ONLY.search(sentence.group(0)):
            for match in _PASSWORDY.finditer(sentence.group(0)):
                word = match.group(0).rstrip(".!?:)\"'")
                if len(word) >= 6:
                    found.append((sentence.start() + match.start(), sentence.start() + match.start() + len(word)))
    return found
_ACCOUNT = re.compile(
    r"(?P<label>\b(?:a/?c|acct|account)(?:\s*(?:no\.?|number|#))?)(?P<sep>\s*[:\-]?\s*)(?P<value>\d{9,18})\b",
    re.I,
)
_AADHAAR = re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_KEYS = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{20,}|nvapi-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{30,}|"
    r"xox[abpr]-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{30,})\b"
)
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        number = int(char)
        if index % 2:
            number *= 2
            if number > 9:
                number -= 9
        total += number
    return total % 10 == 0


def _cards(text: str) -> list[re.Match]:
    found = []
    for match in _CARD.finditer(text or ""):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits) and len(set(digits)) >= 2:
            found.append(match)
    return found


def looks_secret(text: str | None) -> bool:
    """True when the text seems to hold a password, PIN, card, ID or key."""
    if not text:
        return False
    return bool(
        _LABELLED.search(text) or _passwordy(text) or _ACCOUNT.search(text) or _KEYS.search(text)
        or (_AADHAAR.search(text) and re.search(r"\baadh?aa?r\b", text, re.I))
        or _PAN.search(text) or _cards(text)
        or (_IFSC.search(text) and re.search(r"\d{9,18}", text))
    )


def mask_secrets(text: str | None) -> str:
    """The text with secret values replaced by ••••, labels kept."""
    if not text:
        return text or ""
    masked = _LABELLED.sub(lambda m: f"{m.group('label')}{m.group('sep')}{MASK}", text)
    for start, end in sorted(_passwordy(masked), reverse=True):
        masked = masked[:start] + MASK + masked[end:]
    masked = _ACCOUNT.sub(lambda m: f"{m.group('label')}{m.group('sep')}{MASK}", masked)
    masked = _KEYS.sub(MASK, masked)
    masked = _PAN.sub(MASK, masked)
    for match in sorted(_cards(masked), key=lambda m: m.start(), reverse=True):
        tail = " " if match.group(0).endswith(" ") else ""
        masked = masked[: match.start()] + MASK + tail + masked[match.end():]
    if re.search(r"\baadh?aa?r\b", masked, re.I):
        masked = _AADHAAR.sub(MASK, masked)
    return masked
