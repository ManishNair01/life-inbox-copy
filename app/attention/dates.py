"""Date/deadline phrase normalization for attention views."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def configured_timezone() -> ZoneInfo:
    name = os.getenv("LIFE_INBOX_TIMEZONE", "UTC").strip() or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def today_in_configured_tz() -> date:
    return datetime.now(configured_timezone()).date()


@dataclass
class ParsedTiming:
    original_phrase: str
    due_date: Optional[date]
    confidence: str  # high | medium | low | none
    needs_confirmation: bool
    normalized_iso: Optional[str]
    note: Optional[str] = None
    time_of_day: Optional[str] = None
    # True when the words name the day itself ("today", "tomorrow", "12 Nov",
    # "2026-11-12", "in 3 days"); False for a guess ("this weekend", "Friday",
    # "in December", "ASAP"). Change 012: named days go straight on the
    # calendar as "from your note"; guesses wait for your OK.
    explicit: bool = False


_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_MDY = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(20\d{2}))?\b",
    re.I,
)
_DMY = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)(?:,?\s*(20\d{2}))?\b",
    re.I,
)
_MONTH_ONLY = re.compile(
    r"\b(?:in|during|sometime in|by)?\s*"
    r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)(?:\s+(20\d{2}))?\b",
    re.I,
)
_IN_DAYS = re.compile(r"\bin\s+(\d+)\s+days?\b", re.I)
# "by 5th", "before the 15th", "on the 3rd": a day of the month without the
# month (change 014). Only after one of these words, so "3rd floor" isn't a date.
_ORDINAL_DAY = re.compile(
    r"\b(?:by|before|on|due|till|until)\s+(?:the\s+)?(\d{1,2})(?:st|nd|rd|th)\b", re.I
)
_WEEKDAY = re.compile(
    r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.I,
)
_TIME = re.compile(
    r"\b((?:[01]?\d|2[0-3]):[0-5]\d(?:\s*(?:am|pm))?|(?:1[0-2]|0?[1-9])\s*(?:am|pm))\b",
    re.I,
)

_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def extract_time_of_day(phrase: Optional[str]) -> Optional[str]:
    if not phrase:
        return None
    match = _TIME.search(phrase)
    return match.group(1).strip() if match else None


def normalize_time_of_day(phrase: Optional[str]) -> Optional[str]:
    """Normalize an explicit time phrase to local 24-hour HH:MM."""
    extracted = extract_time_of_day(phrase)
    if extracted is None:
        return None

    value = extracted.lower().replace(" ", "")
    suffix = value[-2:] if value.endswith(("am", "pm")) else None
    clock = value[:-2] if suffix else value
    if ":" in clock:
        hour_text, minute_text = clock.split(":", 1)
    else:
        hour_text, minute_text = clock, "00"

    try:
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError:
        return None
    if minute > 59:
        return None

    if suffix:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if suffix == "pm" else 0)
    elif not 0 <= hour <= 23:
        return None

    return f"{hour:02d}:{minute:02d}"


def parse_timing_phrase(
    phrase: Optional[str],
    *,
    reference: Optional[date] = None,
) -> ParsedTiming:
    original = (phrase or "").strip()
    if not original:
        return ParsedTiming(
            original_phrase="",
            due_date=None,
            confidence="none",
            needs_confirmation=False,
            normalized_iso=None,
            note="No timing phrase.",
        )

    ref = reference or today_in_configured_tz()
    lower = original.lower()
    time_of_day = extract_time_of_day(original)

    if "asap" in lower or "urgent" in lower:
        return ParsedTiming(
            original_phrase=original,
            due_date=ref,
            confidence="low",
            needs_confirmation=True,
            normalized_iso=ref.isoformat(),
            note="Urgent/ASAP treated as today but needs confirmation.",
            time_of_day=time_of_day,
        )

    # "tonight" / "this evening" etc. all mean today (the time stays in time_of_day).
    if re.search(r"\b(today|tonight|this (?:morning|afternoon|evening))\b", lower):
        return ParsedTiming(
            original_phrase=original,
            due_date=ref,
            confidence="high",
            needs_confirmation=False,
            normalized_iso=ref.isoformat(),
            time_of_day=time_of_day,
            explicit=True,
        )

    if re.search(r"\btomorrow\b", lower):
        due = ref + timedelta(days=1)
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence="high",
            needs_confirmation=False,
            normalized_iso=due.isoformat(),
            time_of_day=time_of_day,
            explicit=True,
        )

    if "this weekend" in lower or "weekend" in lower:
        # Next Saturday from ref (or today if Saturday).
        days_ahead = (5 - ref.weekday()) % 7
        due = ref + timedelta(days=days_ahead)
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence="medium",
            needs_confirmation=True,
            normalized_iso=due.isoformat(),
            note="Weekend normalized to Saturday; confirm if needed.",
            time_of_day=time_of_day,
        )

    iso = _ISO.search(original)
    if iso:
        due = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence="high",
            needs_confirmation=False,
            normalized_iso=due.isoformat(),
            time_of_day=time_of_day,
            explicit=True,
        )

    in_days = _IN_DAYS.search(original)
    if in_days:
        due = ref + timedelta(days=int(in_days.group(1)))
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence="high",
            needs_confirmation=False,
            normalized_iso=due.isoformat(),
            time_of_day=time_of_day,
            explicit=True,
        )

    mdy = _MDY.search(original)
    if mdy:
        month = _MONTHS[mdy.group(1).lower()]
        day = int(mdy.group(2))
        year = int(mdy.group(3)) if mdy.group(3) else ref.year
        try:
            due = date(year, month, day)
        except ValueError:
            return ParsedTiming(
                original_phrase=original,
                due_date=None,
                confidence="low",
                needs_confirmation=True,
                normalized_iso=None,
                note="Could not parse calendar date.",
                time_of_day=time_of_day,
            )
        if mdy.group(3) is None and due < ref:
            due = date(year + 1, month, day)
        confidence = "high" if mdy.group(3) else "medium"
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence=confidence,
            needs_confirmation=confidence != "high",
            normalized_iso=due.isoformat(),
            note=None if confidence == "high" else "Year inferred; confirm.",
            time_of_day=time_of_day,
            explicit=True,
        )

    dmy = _DMY.search(original)
    if dmy:
        day = int(dmy.group(1))
        month = _MONTHS[dmy.group(2).lower()]
        year = int(dmy.group(3)) if dmy.group(3) else ref.year
        try:
            due = date(year, month, day)
        except ValueError:
            return ParsedTiming(
                original_phrase=original,
                due_date=None,
                confidence="low",
                needs_confirmation=True,
                normalized_iso=None,
                note="Could not parse calendar date.",
                time_of_day=time_of_day,
            )
        if dmy.group(3) is None and due < ref:
            due = date(year + 1, month, day)
        confidence = "high" if dmy.group(3) else "medium"
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence=confidence,
            needs_confirmation=confidence != "high",
            normalized_iso=due.isoformat(),
            note=None if confidence == "high" else "Year inferred; confirm.",
            time_of_day=time_of_day,
            explicit=True,
        )

    weekday = _WEEKDAY.search(original)
    if weekday:
        target = _WEEKDAYS[weekday.group(2).lower()]
        days_ahead = (target - ref.weekday()) % 7
        if days_ahead == 0 or weekday.group(1):
            days_ahead = 7 if days_ahead == 0 else days_ahead
            if weekday.group(1) and days_ahead < 7:
                days_ahead += 7
        due = ref + timedelta(days=days_ahead or 7)
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence="medium",
            needs_confirmation=True,
            normalized_iso=due.isoformat(),
            note="Weekday timing is ambiguous; confirm the intended date.",
            time_of_day=time_of_day,
        )

    ordinal = _ORDINAL_DAY.search(original)
    if ordinal and 1 <= int(ordinal.group(1)) <= 31:
        # The next date with that day number; the month is a guess, so it is
        # a suggestion that waits for your OK (explicit stays False).
        wanted = int(ordinal.group(1))
        year, month = ref.year, ref.month
        if wanted < ref.day:
            month += 1
        for _ in range(13):
            if month > 12:
                year, month = year + 1, 1
            try:
                due = date(year, month, wanted)
                break
            except ValueError:  # e.g. the 31st in a 30-day month
                month += 1
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence="medium",
            needs_confirmation=True,
            normalized_iso=due.isoformat(),
            note="A day of the month without the month; the next one. Needs confirmation.",
            time_of_day=time_of_day,
        )

    month_only = _MONTH_ONLY.search(original)
    if month_only:
        month = _MONTHS[month_only.group(1).lower()]
        year = int(month_only.group(2)) if month_only.group(2) else ref.year
        if month_only.group(2) is None and (year < ref.year or (year == ref.year and month < ref.month)):
            year += 1
        due = date(year, month, 1)
        return ParsedTiming(
            original_phrase=original,
            due_date=due,
            confidence="low",
            needs_confirmation=True,
            normalized_iso=due.isoformat(),
            note="Month only; normalized to the 1st of the month. Needs confirmation.",
            time_of_day=time_of_day,
        )

    return ParsedTiming(
        original_phrase=original,
        due_date=None,
        confidence="low",
        needs_confirmation=True,
        normalized_iso=None,
        note="Could not confidently normalize this timing phrase.",
        time_of_day=time_of_day,
    )


def date_source(parsed: ParsedTiming) -> Optional[str]:
    """Where a task's date stands (change 012): "from_note" when your words name
    the day, "suggested" when Life Inbox had to guess it, None for no date."""
    if not parsed.normalized_iso:
        return None
    return "from_note" if parsed.explicit else "suggested"


def classify_attention_bucket(
    due: Optional[date],
    *,
    reference: Optional[date] = None,
    snoozed_until: Optional[date] = None,
) -> str:
    ref = reference or today_in_configured_tz()
    if snoozed_until and snoozed_until > ref:
        return "snoozed"
    if due is None:
        return "unscheduled"
    if due < ref:
        return "overdue"
    if due == ref:
        return "today"
    return "upcoming"
