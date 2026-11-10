"""The least information a tool needs from the owner, such as an event's title and time."""

from datetime import datetime, timedelta, timezone

import pytest

from src.backend.integrations.prerequisites import Prerequisite, Prerequisites, missing_message

EVENT_TOOL = {
    "name": "create_event",
    "_meta": {
        "prerequisites": [
            {"field": "summary", "name": "event title", "from_owner": True},
            {"field": "start", "name": "time", "needs": "time", "from_owner": True},
        ]
    },
}


OWNER = "add another event tm at 1:20 saying go to dhur @ OPPC"
EVENT = {"summary": "Go to Dhur at OPPC", "start": "2026-11-11T13:20:00-06:00"}


def test_title_and_time_from_the_owner_mean_nothing_missing():
    assert Prerequisites.from_tool(EVENT_TOOL).missing(EVENT, OWNER) == []


def test_a_time_the_owner_never_said_is_missing():
    assert Prerequisites.from_tool(EVENT_TOOL).missing({**EVENT, "start": "2026-11-11T09:00:00-06:00"}, OWNER) == [
        "time"
    ]


def test_a_title_with_words_the_owner_never_said_is_missing():
    assert Prerequisites.from_tool(EVENT_TOOL).missing({**EVENT, "summary": "Prayer at OPPC"}, OWNER) == [
        "event title"
    ]


def test_no_time_in_the_owner_message_means_the_time_is_missing():
    owner = "add an event tomorrow saying go to dhur @ OPPC"
    assert Prerequisites.from_tool(EVENT_TOOL).missing(EVENT, owner) == ["time"]


@pytest.mark.parametrize(
    ("said", "start"),
    [
        ("at 3pm", "T15:00"),
        ("at 3 p.m.", "T15:00"),
        ("1:20pm", "T13:20"),
        ("at 9", "T09:00"),
        ("at 9", "T21:00"),
        ("noon", "T12:00"),
        ("9:30 am", "T09:30"),
        ("at 630", "T18:30"),
        ("630pm", "T18:30"),
        ("at 1130", "T11:30"),
        ("half past 3", "T15:30"),
        ("quarter to 4", "T15:45"),
        ("quarter past six", "T06:15"),
        ("six thirty", "T18:30"),
        ("8 o'clock", "T20:00"),
        ("10 minutes past 5", "T17:10"),
        ("10 to 12", "T11:50"),
        ("@3pm", "T15:00"),
        ("at six", "T18:00"),
    ],
)
def test_common_ways_of_saying_a_time(said, start):
    item = Prerequisite("start", "time", "time", from_owner=True)
    assert item.is_given({"start": f"2026-11-11{start}:00-06:00"}, said)


@pytest.mark.parametrize(
    ("said", "start"),
    [("at 3pm", "T03:00"), ("9:30 am", "T21:30"), ("on the 15th", "T15:00"), ("nov 11 2026", "T20:26")],
)
def test_times_that_do_not_match(said, start):
    item = Prerequisite("start", "time", "time", from_owner=True)
    assert not item.is_given({"start": f"2026-11-11{start}:00-06:00"}, said)


def test_missing_title_and_time_are_named():
    assert Prerequisites.from_tool(EVENT_TOOL).missing({"summary": "  "}) == ["event title", "time"]


def test_a_date_without_a_time_does_not_count_as_a_time():
    assert Prerequisites.from_tool(EVENT_TOOL).missing({**EVENT, "start": "2026-11-11"}, OWNER) == ["time"]


def test_tools_without_a_declaration_need_nothing():
    needed = Prerequisites.from_tool({"name": "list_events"})
    assert needed.missing({}) == []
    assert needed.description() == ""


def test_malformed_declarations_are_skipped():
    tool = {"_meta": {"prerequisites": ["summary", {"name": "no field"}, {"field": "start"}]}}
    assert Prerequisites.from_tool(tool).missing({}) == ["start"]


def test_model_is_told_up_front_and_when_blocked():
    assert "event title, time" in Prerequisites.from_tool(EVENT_TOOL).description()
    assert "event title" in missing_message(["event title"])


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone(timedelta(hours=-6)))


@pytest.mark.parametrize(
    ("said", "start"),
    [("in 15 minutes", "12:15"), ("2 hours from now", "14:00"), ("in half an hour", "12:30"), ("in an hour", "13:00")],
)
def test_times_from_now(said, start):
    item = Prerequisite("start", "time", "time", from_owner=True)
    assert item.is_given({"start": f"2026-11-10T{start}:00-06:00"}, said, NOW)


def test_a_time_from_now_must_match_what_was_said():
    item = Prerequisite("start", "time", "time", from_owner=True)
    assert not item.is_given({"start": "2026-11-10T15:00:00-06:00"}, "in 15 minutes", NOW)
