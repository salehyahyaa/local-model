import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from src.backend.integrations import env_secrets, mcp_store, service
from src.backend.integrations.errors import DuplicateNameError
from src.backend.integrations.google_calendar import api, server, sign_in
from src.backend.integrations.oauth import OAuthError
from src.backend.integrations.validation import validate_google_calendar_connection
from src.backend.main import app

client = TestClient(app)
CLIENT_ID = "abc.apps.googleusercontent.com"
BODY = {"clientId": CLIENT_ID, "clientSecret": "shh"}
EVENT = {
    "id": "e1",
    "summary": "Dentist",
    "start": {"dateTime": "2026-11-10T14:00:00-06:00"},
    "end": {"dateTime": "2026-11-10T15:00:00-06:00"},
    "attendees": [{"email": "a@example.com"}],
    "etag": "not needed",
}


def recording_transport(seen, response=None):
    def handler(request):
        seen.append(request)
        return response or httpx.Response(200, json=EVENT)

    return httpx.MockTransport(handler)


# Tools the model can use


def tool_annotations():
    return {tool["name"]: tool.get("annotations", {}) for tool in server.TOOLS}


def test_only_reading_the_calendar_skips_approval():
    annotations = tool_annotations()
    assert annotations["list_events"] == {"readOnlyHint": True}
    assert annotations["create_event"] == {}
    assert annotations["update_event"] == {}
    assert annotations["delete_event"] == {}


def test_listing_expands_repeats_and_keeps_only_useful_fields():
    seen = []
    response = httpx.Response(200, json={"items": [EVENT]})
    events = api.list_events("tok", limit=500, transport=recording_transport(seen, response))
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert seen[0].url.params["singleEvents"] == "true"
    assert seen[0].url.params["maxResults"] == str(api.MAX_LIMIT)
    assert "calendars/primary/events" in str(seen[0].url)
    assert events[0]["id"] == "e1"
    assert events[0]["has_guests"] is True
    assert "etag" not in events[0]


def test_creating_sends_the_event():
    seen = []
    arguments = {"summary": "Lunch", "start": "2026-11-10T12:00:00-06:00", "end": "2026-11-10"}
    created = api.create_event("tok", arguments, recording_transport(seen))
    body = json.loads(seen[0].content)
    assert seen[0].method == "POST"
    assert body["start"] == {"dateTime": "2026-11-10T12:00:00-06:00"}
    assert body["end"] == {"date": "2026-11-10"}
    assert created["id"] == "e1"


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"summary": "Lunch", "start": "2026-11-10T12:00:00-06:00"},
        {"summary": "Lunch", "start": "2pm", "end": "3pm"},
        {"summary": "Lunch", "start": "2026-11-10T12:00:00", "end": "2026-11-10T13:00:00"},
    ],
)
def test_incomplete_or_unclear_events_are_never_sent(arguments):
    seen = []
    with pytest.raises(api.CalendarError):
        api.create_event("tok", arguments, recording_transport(seen))
    assert seen == []


def test_moving_sends_only_what_changes():
    seen = []
    api.update_event("tok", {"event_id": "e1", "start": "2026-11-10"}, recording_transport(seen))
    assert seen[0].method == "PATCH"
    assert json.loads(seen[0].content) == {"start": {"date": "2026-11-10"}}


def test_changing_nothing_is_refused():
    seen = []
    with pytest.raises(api.CalendarError):
        api.update_event("tok", {"event_id": "e1"}, recording_transport(seen))
    assert seen == []


def test_event_ids_cannot_reach_another_address():
    seen = []
    api.delete_event("tok", {"event_id": "../../other"}, recording_transport(seen, httpx.Response(204)))
    assert seen[0].method == "DELETE"
    assert seen[0].url.raw_path.endswith(b"/events/..%2F..%2Fother")


@pytest.mark.parametrize("event_id", [None, "", "  ", 5])
def test_missing_event_id_is_refused(event_id):
    with pytest.raises(api.CalendarError):
        api.delete_event("tok", {"event_id": event_id}, recording_transport([]))


@pytest.mark.parametrize(("status", "text"), [(401, "connect it again"), (403, "turned on"), (404, "find"), (500, "500")])
def test_google_errors_are_explained(status, text):
    with pytest.raises(api.CalendarError) as error:
        api.list_events("tok", transport=recording_transport([], httpx.Response(status)))
    assert text in str(error.value)


def test_errors_reach_the_model_without_stopping_the_server(monkeypatch):
    def broken():
        raise api.CalendarError("No sign-in")

    monkeypatch.setattr(server, "access_token", broken)
    result = server.call_tool({"name": "list_events", "arguments": {}})
    assert result == {"content": [{"type": "text", "text": "No sign-in"}], "isError": True}


def test_unknown_tool_is_an_error():
    assert server.call_tool({"name": "nope"})["isError"] is True


def test_server_lists_its_tools():
    response = server.handle_line(json.dumps({"id": 1, "method": "tools/list"}))
    assert {tool["name"] for tool in response["result"]["tools"]} == set(server.HANDLERS)


# Staying signed in


def test_refreshing_uses_the_saved_sign_in():
    seen = []
    token = api.get_access_token("id", "secret", "refresh", recording_transport(seen, httpx.Response(200, json={"access_token": "new"})))
    assert token == "new"
    form = parse_qs(seen[0].content.decode())
    assert form["grant_type"] == ["refresh_token"]
    assert form["refresh_token"] == ["refresh"]


def test_revoked_sign_in_says_to_connect_again():
    transport = recording_transport([], httpx.Response(400, json={"error": "invalid_grant"}))
    with pytest.raises(api.CalendarError) as error:
        api.get_access_token("id", "secret", "gone", transport)
    assert str(error.value) == api.EXPIRED_MESSAGE


def test_unreachable_google_is_not_reported_as_a_bad_sign_in():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(api.CalendarError) as error:
        api.get_access_token("id", "secret", "refresh", httpx.MockTransport(handler))
    assert str(error.value) == "Couldn't reach Google."


# Signing in


def begin_sign_in():
    return urlparse(sign_in.begin(CLIENT_ID, "shh", "http://127.0.0.1:8000/callback"))


def test_sign_in_asks_for_lasting_calendar_access():
    query = parse_qs(begin_sign_in().query)
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["scope"] == [sign_in.SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    assert "shh" not in str(query)


def fake_google(monkeypatch, tokens=None, token_error=None, list_error=None):
    def request_tokens(form):
        if token_error:
            raise token_error
        return tokens or {"access_token": "a", "refresh_token": "r"}

    def find_account(token):
        if list_error:
            raise list_error
        return "me@example.com"

    monkeypatch.setattr(api, "request_tokens", request_tokens)
    monkeypatch.setattr(api, "find_account", find_account)


def finish(state, code="code"):
    return asyncio.run(sign_in.finish(state, code))


def begin_and_get_state():
    return parse_qs(begin_sign_in().query)["state"][0]


def test_finishing_returns_the_lasting_sign_in(monkeypatch):
    fake_google(monkeypatch)
    assert finish(begin_and_get_state()) == (CLIENT_ID, "shh", "r", "me@example.com")


@pytest.mark.parametrize(
    ("answer", "account"),
    [
        ({"summary": "Plans", "items": [{"creator": {"email": "me@x.com", "self": True}}]}, "me@x.com"),
        ({"summary": "Plans", "items": [{"organizer": {"email": "me@x.com", "self": True}}]}, "me@x.com"),
        ({"summary": "Plans", "items": [{"creator": {"email": "friend@x.com"}}]}, None),
        ({"summary": "me@x.com", "items": []}, "me@x.com"),
        ({"summary": "Plans", "items": []}, None),
    ],
)
def test_finding_the_account_ignores_other_people(answer, account):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=answer))
    assert api.find_account("token", transport) == account


def test_sign_in_state_only_works_once(monkeypatch):
    fake_google(monkeypatch)
    state = begin_and_get_state()
    finish(state)
    with pytest.raises(OAuthError):
        finish(state)


def test_unknown_state_is_refused(monkeypatch):
    fake_google(monkeypatch)
    with pytest.raises(OAuthError):
        finish("made-up")


def test_sign_in_without_lasting_access_is_refused(monkeypatch):
    fake_google(monkeypatch, tokens={"access_token": "a"})
    with pytest.raises(OAuthError):
        finish(begin_and_get_state())


def test_calendar_that_cannot_be_read_is_never_accepted(monkeypatch):
    fake_google(monkeypatch, list_error=api.CalendarError("Google refused this (HTTP 403)."))
    with pytest.raises(OAuthError) as error:
        finish(begin_and_get_state())
    assert "403" in str(error.value)


def test_rejected_client_gets_a_useful_message(monkeypatch):
    fake_google(monkeypatch, token_error=api.CalendarError(api.EXPIRED_MESSAGE))
    with pytest.raises(OAuthError) as error:
        finish(begin_and_get_state())
    assert "client ID and secret" in str(error.value)


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"clientId": "abc", "clientSecret": "shh"},
        {"clientId": CLIENT_ID, "clientSecret": "  "},
        {"clientId": 5, "clientSecret": "shh"},
    ],
)
def test_invalid_client_details_are_rejected(body):
    connection, error = validate_google_calendar_connection(body)
    assert connection is None
    assert error


# Saving and routes


@pytest.fixture
def saved(monkeypatch):
    secrets = {}
    records = []

    async def create_server(record):
        records.append(record)
        return {"id": 1, "enabled": True, **record}

    async def finish_sign_in(state, code):
        return CLIENT_ID, "shh", "refresh", "me@example.com"

    monkeypatch.setattr(mcp_store, "create_server", create_server)
    monkeypatch.setattr(sign_in, "finish", finish_sign_in)
    monkeypatch.setattr(env_secrets, "secret_exists", lambda name: name in secrets)
    monkeypatch.setattr(env_secrets, "save_secret", secrets.__setitem__)
    return secrets, records


def test_saving_keeps_secrets_out_of_the_database(saved):
    secrets, records = saved
    created = asyncio.run(service.finish_google_calendar_sign_in("state", "code"))
    assert created["provider"] == "google-calendar"
    assert created["target"] == "me@example.com"
    assert set(secrets.values()) == {"shh", "refresh"}
    stored = json.dumps(records[0])
    assert "shh" not in stored
    assert "refresh" not in stored.replace("REFRESH_TOKEN", "")
    assert records[0]["args"] == service.GOOGLE_CALENDAR_SERVER_ARGS


def test_route_returns_the_sign_in_address(monkeypatch):
    async def list_servers():
        return []

    monkeypatch.setattr(mcp_store, "list_servers", list_servers)
    response = client.post("/api/integrations/google-calendar", json=BODY)
    assert response.status_code == 201
    assert response.json()["authorizationUrl"].startswith(sign_in.AUTHORIZATION_URL)
    query = parse_qs(urlparse(response.json()["authorizationUrl"]).query)
    assert query["redirect_uri"][0].endswith("/api/integrations/google-calendar/callback")


def test_route_refuses_a_second_connection(monkeypatch):
    async def begin(connection, redirect_uri):
        raise DuplicateNameError("Google Calendar")

    monkeypatch.setattr(service, "begin_google_calendar_sign_in", begin)
    assert client.post("/api/integrations/google-calendar", json=BODY).status_code == 409


def test_route_validates_the_form():
    assert client.post("/api/integrations/google-calendar", json={"clientId": "x"}).status_code == 422


def test_other_websites_cannot_start_a_sign_in():
    response = client.post(
        "/api/integrations/google-calendar", json=BODY, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_callback_reports_a_finished_sign_in(monkeypatch):
    async def finish_sign_in(state, code):
        return {}

    monkeypatch.setattr(service, "finish_google_calendar_sign_in", finish_sign_in)
    page = client.get("/api/integrations/google-calendar/callback?state=s&code=c").text
    assert "Signed in" in page
    assert "mcp-sign-in" in page


def test_callback_handles_a_cancelled_sign_in():
    page = client.get("/api/integrations/google-calendar/callback?error=access_denied").text
    assert "cancelled" in page
    assert "mcp-sign-in" not in page


def test_callback_escapes_problems(monkeypatch):
    async def finish_sign_in(state, code):
        raise OAuthError("<b>bad</b>")

    monkeypatch.setattr(service, "finish_google_calendar_sign_in", finish_sign_in)
    page = client.get("/api/integrations/google-calendar/callback?state=s&code=c").text
    assert "<b>" not in page


# Showing a broken connection in the + menu


CALENDAR_SERVER = {
    "id": 7,
    "enabled": True,
    "args": service.GOOGLE_CALENDAR_SERVER_ARGS,
    "env": {"GOOGLE_CLIENT_ID": "i", "GOOGLE_CLIENT_SECRET": "s", "GOOGLE_REFRESH_TOKEN": "r"},
}


def test_revoked_calendar_shows_as_broken(monkeypatch):
    monkeypatch.setattr(env_secrets, "resolve_mapping", lambda mapping: mapping)

    def revoked(client_id, client_secret, refresh_token):
        raise api.CalendarError(api.EXPIRED_MESSAGE)

    monkeypatch.setattr(api, "get_access_token", revoked)
    status = asyncio.run(service.find_problem("mcp", 7, service.check_mcp_server(CALENDAR_SERVER)))
    assert status == {"kind": "mcp", "id": 7, "problem": api.EXPIRED_MESSAGE}


def test_working_calendar_has_no_problem(monkeypatch):
    monkeypatch.setattr(env_secrets, "resolve_mapping", lambda mapping: mapping)
    monkeypatch.setattr(api, "get_access_token", lambda client_id, client_secret, refresh_token: "token")
    status = asyncio.run(service.find_problem("mcp", 7, service.check_mcp_server(CALENDAR_SERVER)))
    assert status["problem"] is None


def test_page_includes_the_calendar_form():
    page = client.get("/").text
    assert 'id="google-calendar-dialog"' in page
    assert 'id="add-google-calendar-button"' in page
