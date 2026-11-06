from fastapi.testclient import TestClient

from src.backend import db, integration_routes
from src.backend.integrations import mcp_store, service
from src.backend.integrations.errors import DuplicateNameError, McpError
from src.backend.main import app

client = TestClient(app)


def test_list_without_database_returns_503(monkeypatch):
    monkeypatch.setattr(db, "pool", None)
    response = client.get("/api/integrations")
    assert response.status_code == 503


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
