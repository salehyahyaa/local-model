"""Talks to Google Calendar with plain HTTP calls. Tokens stay out of error text and logs."""

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_PATH = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
TIMEOUT = 20
DEFAULT_DAYS_AHEAD = 7
DEFAULT_LIMIT = 25
MAX_LIMIT = 100
EVENTS_TO_CHECK_FOR_ACCOUNT = 250
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EXPIRED_MESSAGE = "The Google sign-in is no longer valid. Remove Google Calendar and connect it again."


class CalendarError(Exception):
    """Its text is safe to show."""


def request_tokens(form, transport=None):
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            response = client.post(TOKEN_URL, data=form)
        tokens = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise CalendarError("Couldn't reach Google.") from error
    if response.is_error or not isinstance(tokens, dict) or not tokens.get("access_token"):
        raise CalendarError(EXPIRED_MESSAGE)
    return tokens


def get_access_token(client_id, client_secret, refresh_token, transport=None):
    form = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    return request_tokens(form, transport)["access_token"]


def error_for(response):
    if response.status_code == 401:
        return CalendarError(EXPIRED_MESSAGE)
    if response.status_code == 403:
        return CalendarError("Google refused this (HTTP 403). Check that the Google Calendar API is turned on.")
    if response.status_code == 404:
        return CalendarError("Google couldn't find that event.")
    return CalendarError(f"Google Calendar had a problem (HTTP {response.status_code}).")


def call(token, method, url, params=None, body=None, transport=None):
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            response = client.request(method, url, params=params, json=body, headers=headers)
    except httpx.HTTPError as error:
        raise CalendarError("Couldn't reach Google Calendar.") from error
    if response.is_error:
        raise error_for(response)
    if not response.content:
        return {}
    try:
        return response.json()
    except ValueError as error:
        raise CalendarError("Google Calendar sent an answer that couldn't be read.") from error


def read_time(value, label):
    """All-day events use a date. Other times must state their UTC offset, so an hour can't silently shift."""
    if not isinstance(value, str):
        raise CalendarError(f"{label} is required.")
    text = value.strip()
    if DATE_PATTERN.match(text):
        return {"date": text}
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as error:
        raise CalendarError(f"{label} must be a date or an ISO 8601 time with a UTC offset.") from error
    if parsed.utcoffset() is None:
        raise CalendarError(f"{label} must include a UTC offset, like 2026-11-10T14:00:00-06:00.")
    return {"dateTime": text}


def event_url(event_id):
    if not isinstance(event_id, str) or not event_id.strip():
        raise CalendarError("event_id is required.")
    return f"{EVENTS_PATH}/{quote(event_id.strip(), safe='')}"


def to_public(event):
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "start": event.get("start"),
        "end": event.get("end"),
        "location": event.get("location"),
        "description": event.get("description"),
        "has_guests": bool(event.get("attendees")),
    }


def read_limit(value):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(limit, MAX_LIMIT))


def list_events(token, time_min=None, time_max=None, query=None, limit=DEFAULT_LIMIT, transport=None):
    now = datetime.now(timezone.utc)
    params = {
        "singleEvents": "true",
        "orderBy": "startTime",
        "timeMin": time_min or now.isoformat(),
        "timeMax": time_max or (now + timedelta(days=DEFAULT_DAYS_AHEAD)).isoformat(),
        "maxResults": read_limit(limit),
    }
    if query:
        params["q"] = str(query)
    found = call(token, "GET", EVENTS_PATH, params=params, transport=transport)
    return [to_public(event) for event in found.get("items", [])]


def find_account(token, transport=None):
    """Returns the signed-in address, or None if the calendar doesn't show it. This access can't ask Google directly."""
    found = call(token, "GET", EVENTS_PATH, params={"maxResults": EVENTS_TO_CHECK_FOR_ACCOUNT}, transport=transport)
    for event in found.get("items", []):
        for person in (event.get("creator") or {}, event.get("organizer") or {}):
            if person.get("self") and person.get("email"):
                return person["email"]
    title = found.get("summary")
    return title if isinstance(title, str) and "@" in title else None


def event_fields(arguments):
    fields = {name: str(arguments[name]) for name in ("summary", "location", "description") if name in arguments}
    if "start" in arguments:
        fields["start"] = read_time(arguments["start"], "start")
    if "end" in arguments:
        fields["end"] = read_time(arguments["end"], "end")
    return fields


def create_event(token, arguments, transport=None):
    fields = event_fields(arguments)
    if "summary" not in fields or "start" not in fields or "end" not in fields:
        raise CalendarError("summary, start and end are required.")
    return to_public(call(token, "POST", EVENTS_PATH, body=fields, transport=transport))


def update_event(token, arguments, transport=None):
    url = event_url(arguments.get("event_id"))
    fields = event_fields(arguments)
    if not fields:
        raise CalendarError("Say what should change.")
    return to_public(call(token, "PATCH", url, body=fields, transport=transport))


def delete_event(token, arguments, transport=None):
    call(token, "DELETE", event_url(arguments.get("event_id")), transport=transport)
