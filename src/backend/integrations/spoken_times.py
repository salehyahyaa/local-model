"""Finds the times of day the owner wrote, in the ways people write them, so a tool can check a time came from them.

Clock times: 1:20, 1:20pm, 630, 3pm, 3 p.m., at 3, at six, 8 o'clock, six thirty, half past 3, quarter to 4,
10 minutes past 5, noon, midnight. Relative times: in 15 minutes, in an hour, in half an hour, 2 hours from now.
"""

import re
from datetime import datetime, timedelta

# Relative times are worked out by the model too, so its answer can be off by a little rounding.
RELATIVE_TOLERANCE = timedelta(minutes=5)

NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "a": 1, "an": 1,
}  # fmt: skip
HOUR = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
MINUTE_WORDS = r"(o\s+five|ten|fifteen|twenty|twenty[\s-]five|thirty|thirty[\s-]five|forty|forty[\s-]five|fifty|fifty[\s-]five)"
AM_PM = r"(?:\s*([ap])\.?\s*m\b\.?)?"

CLOCK = re.compile(rf"\b(\d{{1,2}}):(\d{{2}})(?!\d){AM_PM}")
# 630 or 1130. Four digits only count with "at" or am/pm, so a year like 2026 isn't read as a time.
THREE_DIGITS = re.compile(rf"\b(\d)(\d{{2}})(?!\d){AM_PM}")
FOUR_DIGITS = re.compile(rf"(?:\bat\s+(\d{{2}})(\d{{2}})(?!\d){AM_PM}|\b(\d{{2}})(\d{{2}})\s*([ap])\.?\s*m\b)")
HOUR_AM_PM = re.compile(rf"(?<![:\d]){HOUR}\s*([ap])\.?\s*m\b")
AT_HOUR = re.compile(rf"\bat\s+{HOUR}\b(?!\s*[:/\d])")
OCLOCK = re.compile(rf"\b{HOUR}\s*o'?\s*clock\b")
HOUR_AND_WORDS = re.compile(rf"\b{HOUR}\s+{MINUTE_WORDS}\b")
HALF_OR_QUARTER = re.compile(rf"\b(half|quarter)\s+(past|after|to|til|till|before)\s+{HOUR}\b")
MINUTES_PAST = re.compile(rf"\b(\d{{1,2}}|{MINUTE_WORDS})\s+(?:minutes?\s+)?(past|after|to|til|till|before)\s+{HOUR}\b")
NAMED = {"noon": (12, 0), "midday": (12, 0), "midnight": (0, 0)}
RELATIVE = re.compile(
    r"\b(?:in\s+(\d+|an?|half\s+an?)\s+(minutes?|mins?|hours?|hrs?)\b"
    r"|(\d+|an?|half\s+an?)\s+(minutes?|mins?|hours?|hrs?)\s+from\s+now\b)"
)


def number(text):
    text = re.sub(r"[\s-]+", " ", text.strip())
    if text.isdigit():
        return int(text)
    if text.startswith("o "):
        return NUMBER_WORDS[text[2:]]
    return sum(NUMBER_WORDS[word] for word in text.split())


def clock_times(text):
    """Every clock time written, as (hour, minute, "a"/"p"/None). Without am/pm the hour could be either."""
    found = []
    for h, m, half in CLOCK.findall(text):
        found.append((int(h), int(m), half or None))
    for h, m, half in THREE_DIGITS.findall(text):
        found.append((int(h), int(m), half or None))
    for at_h, at_m, at_half, h, m, half in FOUR_DIGITS.findall(text):
        found.append((int(at_h or h), int(at_m or m), (at_half or half) or None))
    for h, half in HOUR_AM_PM.findall(text):
        found.append((number(h), 0, half))
    for pattern in (AT_HOUR, OCLOCK):
        found += [(number(h), 0, None) for h in pattern.findall(text)]
    for h, m in HOUR_AND_WORDS.findall(text):
        found.append((number(h), number(m), None))
    for amount, direction, h in HALF_OR_QUARTER.findall(text):
        found.append(offset_from_hour(number(h), 30 if amount == "half" else 15, direction))
    for minutes, _, direction, h in MINUTES_PAST.findall(text):
        found.append(offset_from_hour(number(h), number(minutes), direction))
    found += [(hour, minute, None) for name, (hour, minute) in NAMED.items() if re.search(rf"\b{name}\b", text)]
    return [(hour, minute, half) for hour, minute, half in found if hour <= 23 and minute <= 59]


def offset_from_hour(hour, minutes, direction):
    if direction in ("past", "after"):
        return (hour, minutes, None)
    return ((hour - 1) % 12 or 12, 60 - minutes, None)


def relative_times(text, now):
    """Times like "in 15 minutes", worked out from now."""
    found = []
    for in_amount, in_unit, from_amount, from_unit in RELATIVE.findall(text):
        amount, unit = (in_amount, in_unit) if in_unit else (from_amount, from_unit)
        size = 0.5 if amount.startswith("half") else (1 if amount in ("a", "an") else int(amount))
        delta = timedelta(hours=size) if unit.startswith("h") else timedelta(minutes=size)
        found.append(now + delta)
    return found


def same_clock_time(hour, minute, said):
    said_hour, said_minute, half = said
    if said_minute != minute:
        return False
    if half is None:
        return said_hour % 12 == hour % 12
    return (said_hour % 12) + (12 if half == "p" else 0) == hour


def owner_said_time(value, owner_text, now=None):
    """True when the time of day in value (ISO 8601) is one the owner wrote."""
    match = re.search(r"T(\d{2}):(\d{2})", value)
    if match is None:
        return False
    text = owner_text.lower().replace("@", " at ")
    hour, minute = int(match.group(1)), int(match.group(2))
    if any(same_clock_time(hour, minute, said) for said in clock_times(text)):
        return True
    now = now or datetime.now().astimezone()
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return any(abs(when - said) <= RELATIVE_TOLERANCE for said in relative_times(text, now))
