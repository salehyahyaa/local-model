import asyncio

import httpx
from fastapi.testclient import TestClient

from src.backend import db, integration_routes
from src.backend.appointment_calls import client as calls_client
from src.backend.appointment_calls import connection as phone_calls
from src.backend.integrations import api_client, api_store, env_secrets, mcp_store, oauth, service, toolbox
from src.backend.integrations.errors import DuplicateNameError, LoginNotConfirmed, McpError
from src.backend.integrations.gmail import mailbox
from src.backend.main import app

client = TestClient(app)


def test_list_without_database_returns_503(monkeypatch):
    monkeypatch.setattr(db, "pool", None)
    response = client.get("/api/integrations")
    assert response.status_code == 503


def fake_saved_integrations(monkeypatch, servers=(), apis=()):
    async def list_servers():
        return list(servers)

    async def list_apis():
        return list(apis)

    monkeypatch.setattr(mcp_store, "list_servers", list_servers)
    monkeypatch.setattr(api_store, "list_integrations", list_apis)


async def no_phone_connection():
    return []


def saved_server(**changes):
    return {"id": 1, "name": "Git", "enabled": True, "args": [], "transport": "http", **changes}


GMAIL_SERVER = saved_server(
    id=2, args=service.GMAIL_SERVER_ARGS, env={"GMAIL_ADDRESS": "a@gmail.com", "GMAIL_APP_PASSWORD": "pw"}
)


def health(monkeypatch):
    monkeypatch.setattr(phone_calls, "check_health", no_phone_connection)
    return client.get("/api/integrations/health").json()["integrations"]


def test_broken_mcp_server_reports_its_problem(monkeypatch):
    fake_saved_integrations(monkeypatch, [saved_server()])

    async def refresh(server):
        return None

    async def broken(server):
        raise McpError("Server answered HTTP 401. Check the login type and details.")

    monkeypatch.setattr(oauth, "refresh_if_needed", refresh)
    monkeypatch.setattr(toolbox, "check_connection", broken)
    assert health(monkeypatch) == [
        {"kind": "mcp", "id": 1, "problem": "Server answered HTTP 401. Check the login type and details."}
    ]


def test_gmail_is_checked_by_really_signing_in(monkeypatch):
    fake_saved_integrations(monkeypatch, [GMAIL_SERVER])
    monkeypatch.setattr(env_secrets, "resolve_mapping", lambda mapping: mapping)

    def rejected(address, password):
        raise mailbox.GmailLoginError("rejected")

    monkeypatch.setattr(mailbox, "check_login", rejected)
    assert health(monkeypatch) == [{"kind": "mcp", "id": 2, "problem": "Gmail rejected the app password."}]


def test_working_gmail_has_no_problem(monkeypatch):
    fake_saved_integrations(monkeypatch, [GMAIL_SERVER])
    monkeypatch.setattr(env_secrets, "resolve_mapping", lambda mapping: mapping)
    monkeypatch.setattr(mailbox, "check_login", lambda address, password: None)
    assert health(monkeypatch) == [{"kind": "mcp", "id": 2, "problem": None}]


def test_turned_off_connections_are_not_contacted(monkeypatch):
    fake_saved_integrations(monkeypatch, [saved_server(enabled=False)], [{"id": 3, "enabled": False, "headers": {"a": "b"}}])
    assert health(monkeypatch) == []


def test_api_login_failure_is_reported_and_no_login_is_not_checked(monkeypatch):
    fake_saved_integrations(
        monkeypatch,
        apis=[{"id": 3, "enabled": True, "headers": {"X-Key": "k"}}, {"id": 4, "enabled": True, "headers": {}}],
    )

    async def rejected(integration, timeout):
        raise LoginNotConfirmed("That service rejected the login (HTTP 401).")

    monkeypatch.setattr(api_client, "check_login", rejected)
    assert health(monkeypatch) == [
        {"kind": "api", "id": 3, "problem": "That service rejected the login (HTTP 401)."},
        {"kind": "api", "id": 4, "problem": None},
    ]


def test_one_unexpected_failure_does_not_stop_the_other_checks(monkeypatch):
    fake_saved_integrations(monkeypatch, [saved_server(), saved_server(id=5)])

    async def refresh(server):
        return None

    async def check(server):
        if server["id"] == 1:
            raise RuntimeError("secret detail")

    monkeypatch.setattr(oauth, "refresh_if_needed", refresh)
    monkeypatch.setattr(toolbox, "check_connection", check)
    assert health(monkeypatch) == [
        {"kind": "mcp", "id": 1, "problem": "Couldn't check this connection."},
        {"kind": "mcp", "id": 5, "problem": None},
    ]


def phone_check(monkeypatch, api_key="key", settings=None, get_agent_error=None):
    saved = settings if settings is not None else {"id": 9, "enabled": True, "agent_id": "a", "phone_number_id": "p"}

    async def load_connection():
        return saved or None

    async def get_agent(key, agent_id):
        if get_agent_error:
            raise get_agent_error
        return {"conversation_config": {"agent": {"prompt": {"llm": "custom-llm"}}}}

    async def get_phone_number(key, phone_number_id):
        return None

    monkeypatch.setattr(phone_calls, "load_connection", load_connection)
    monkeypatch.setattr(phone_calls, "get_api_key", lambda: api_key)
    monkeypatch.setattr(calls_client, "get_agent", get_agent)
    monkeypatch.setattr(calls_client, "get_phone_number", get_phone_number)
    return asyncio.run(phone_calls.check_health())


def test_working_phone_connection_has_no_problem(monkeypatch):
    assert phone_check(monkeypatch) == [{"kind": "phone", "id": 9, "problem": None}]


def test_rejected_elevenlabs_key_is_reported(monkeypatch):
    request = httpx.Request("GET", "https://elevenlabs.test")
    error = httpx.HTTPStatusError("bad", request=request, response=httpx.Response(401, request=request))
    assert phone_check(monkeypatch, get_agent_error=error)[0]["problem"] == "ElevenLabs rejected the API key."


def test_unreachable_elevenlabs_is_reported(monkeypatch):
    error = httpx.ConnectError("down")
    assert phone_check(monkeypatch, get_agent_error=error)[0]["problem"] == "Couldn't reach ElevenLabs."


def test_no_phone_connection_has_nothing_to_check(monkeypatch):
    assert phone_check(monkeypatch, settings={}) == []


def test_add_mcp_server_validates_input():
    response = client.post("/api/integrations/mcp", json={"name": "x", "transport": "http", "url": "nope"})
    assert response.status_code == 422
    assert "URL" in response.json()["error"]


def test_add_mcp_server_returns_created(monkeypatch):
    async def fake_add(server):
        return {"id": 3, "kind": "mcp", "name": server["name"]}

    monkeypatch.setattr(service, "add_mcp_server", fake_add)
    response = client.post("/api/integrations/mcp", json={"name": "Git", "transport": "http", "url": "https://g.com"})
    assert response.status_code == 201
    assert response.json() == {"id": 3, "kind": "mcp", "name": "Git"}


def test_add_duplicate_returns_409(monkeypatch):
    async def fake_add(server):
        raise DuplicateNameError(server["name"])

    monkeypatch.setattr(service, "add_mcp_server", fake_add)
    response = client.post("/api/integrations/mcp", json={"name": "Git", "transport": "http", "url": "https://g.com"})
    assert response.status_code == 409


def test_failed_connection_is_shown_on_the_form(monkeypatch):
    async def fake_add(server):
        raise McpError("Server answered HTTP 500")

    monkeypatch.setattr(service, "add_mcp_server", fake_add)
    response = client.post("/api/integrations/mcp", json={"name": "Git", "transport": "http", "url": "https://g.com"})
    assert response.status_code == 422
    assert "HTTP 500" in response.json()["error"]


def test_other_websites_cannot_add_integrations(monkeypatch):
    async def fake_add(server):
        raise AssertionError("must not be reached")

    monkeypatch.setattr(service, "add_mcp_server", fake_add)
    response = client.post(
        "/api/integrations/mcp",
        content='{"name": "x", "transport": "stdio", "command": "run"}',
        headers={"Origin": "https://evil.example", "Content-Type": "text/plain"},
    )
    assert response.status_code == 403


def test_local_commands_can_only_be_added_from_this_computer(monkeypatch):
    added = []

    async def fake_add(server):
        added.append(server["command"])
        return {"id": 1}

    monkeypatch.setattr(service, "add_mcp_server", fake_add)
    body = {"name": "x", "transport": "stdio", "command": "run"}
    assert client.post("/api/integrations/mcp", json=body).status_code == 403
    assert added == []

    local_client = TestClient(app, base_url="http://localhost:8000", client=("127.0.0.1", 50000))
    assert local_client.post("/api/integrations/mcp", json=body).status_code == 201
    assert added == ["run"]


def test_sign_in_returns_the_address_to_visit(monkeypatch):
    seen = []

    async def fake_begin(server, redirect_uri):
        seen.append(redirect_uri)
        return "https://auth.example.com/authorize?x=1"

    monkeypatch.setattr(service, "begin_mcp_sign_in", fake_begin)
    body = {"name": "Notes", "transport": "http", "url": "https://x.com/mcp", "authType": "oauth"}
    response = client.post("/api/integrations/mcp", json=body)
    assert response.json() == {"authorizationUrl": "https://auth.example.com/authorize?x=1"}
    assert seen == ["http://testserver/api/integrations/mcp/oauth/callback"]


def test_sign_in_callback_tells_the_app_when_finished(monkeypatch):
    async def fake_finish(state, code):
        assert (state, code) == ("s", "c")

    monkeypatch.setattr(service, "finish_mcp_sign_in", fake_finish)
    response = client.get("/api/integrations/mcp/oauth/callback", params={"state": "s", "code": "c"})
    assert "BroadcastChannel" in response.text


def test_sign_in_callback_escapes_errors(monkeypatch):
    async def fake_finish(state, code):
        raise McpError("<script>bad()</script>")

    monkeypatch.setattr(service, "finish_mcp_sign_in", fake_finish)
    response = client.get("/api/integrations/mcp/oauth/callback", params={"state": "s", "code": "c"})
    assert "<script>" not in response.text


def test_cancelled_sign_in_saves_nothing():
    response = client.get("/api/integrations/mcp/oauth/callback", params={"error": "access_denied"})
    assert "cancelled" in response.text
    assert "BroadcastChannel" not in response.text


def test_add_api_integration_validates_input():
    response = client.post("/api/integrations/api", json={"name": "Weather"})
    assert response.status_code == 422


def test_toggle_unknown_kind_is_rejected():
    response = client.patch("/api/integrations/email/1", json={"enabled": True})
    assert response.status_code == 422


def test_toggle_missing_integration_returns_404(monkeypatch):
    async def fake_set_enabled(server_id, enabled):
        return False

    monkeypatch.setitem(
        integration_routes.ENABLE_FUNCTIONS,
        "mcp",
        fake_set_enabled,
    )
    response = client.patch("/api/integrations/mcp/99", json={"enabled": False})
    assert response.status_code == 404


def test_remove_integration(monkeypatch):
    removed = []

    async def fake_remove(server_id):
        removed.append(server_id)
        return True

    monkeypatch.setitem(
        integration_routes.REMOVE_FUNCTIONS,
        "mcp",
        fake_remove,
    )
    assert client.delete("/api/integrations/mcp/4").status_code == 200
    assert removed == [4]


def test_store_functions_are_used_for_toggles():
    assert integration_routes.ENABLE_FUNCTIONS["mcp"] is mcp_store.set_enabled
