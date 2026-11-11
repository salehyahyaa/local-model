import asyncio
from datetime import datetime, timedelta

from src.backend.scheduled_jobs import repeats, tool


def local(*parts):
    return datetime(*parts).astimezone()


def test_once_never_repeats():
    assert repeats.next_after(local(2026, 11, 10, 18), "once") is None


def test_daily_skips_to_first_future_time():
    start = local(2026, 11, 1, 18)
    assert repeats.next_after(start, "daily", local(2026, 11, 10, 12)) == local(2026, 11, 10, 18)


def test_weekdays_skip_the_weekend():
    friday = local(2026, 11, 13, 9)
    assert repeats.next_after(friday, "weekdays", friday) == local(2026, 11, 16, 9)


def test_monthly_clamps_to_shorter_months():
    assert repeats.next_after(local(2026, 1, 31, 9), "monthly", local(2026, 1, 31, 10)) == local(2026, 2, 28, 9)


def test_schedule_rejects_past_time():
    past = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
    result = asyncio.run(tool.schedule({"title": "Eat", "instruction": "Remind me to eat", "run_at": past, "repeat": "once"}))
    assert result.startswith(tool.NOT_SAVED)


def test_schedule_rejects_time_without_offset():
    result = asyncio.run(tool.schedule({"title": "Eat", "instruction": "x", "run_at": "2030-01-01T09:00", "repeat": "once"}))
    assert "UTC offset" in result


def test_schedule_rejects_unknown_repeat():
    future = (datetime.now().astimezone() + timedelta(days=1)).isoformat()
    result = asyncio.run(tool.schedule({"title": "Eat", "instruction": "x", "run_at": future, "repeat": "hourly"}))
    assert "repeat must be" in result


def test_time_must_come_from_the_owner():
    future = (datetime.now().astimezone() + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    missing = tool.PREREQUISITES.missing({"run_at": future.isoformat()}, "text Chris saying hi")
    assert missing == ["time"]
