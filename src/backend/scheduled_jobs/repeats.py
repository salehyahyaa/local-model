"""Works out when a repeating task runs next. Times are in the Mac's local time, so "every day at 6pm" stays 6pm."""

import calendar
from datetime import datetime, timedelta

ONCE = "once"
REPEATS = [ONCE, "daily", "weekdays", "weekly", "monthly"]
LABELS = {"once": "Once", "daily": "Daily", "weekdays": "Weekdays", "weekly": "Weekly", "monthly": "Monthly"}


def step(moment, repeat):
    local = moment.astimezone().replace(tzinfo=None)
    if repeat == "daily":
        local += timedelta(days=1)
    elif repeat == "weekly":
        local += timedelta(days=7)
    elif repeat == "weekdays":
        local += timedelta(days=1)
        while local.weekday() >= 5:
            local += timedelta(days=1)
    elif repeat == "monthly":
        month = local.month % 12 + 1
        year = local.year + (local.month == 12)
        day = min(local.day, calendar.monthrange(year, month)[1])
        local = local.replace(year=year, month=month, day=day)
    return local.astimezone()


def next_after(moment, repeat, now=None):
    """The first run after now. None for a one-off task, which doesn't run again."""
    if repeat == ONCE:
        return None
    now = now or datetime.now().astimezone()
    upcoming = step(moment, repeat)
    while upcoming <= now:
        upcoming = step(upcoming, repeat)
    return upcoming
