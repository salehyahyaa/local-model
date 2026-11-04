from fastapi.testclient import TestClient

from src.backend import db, integration_routes
from src.backend.integrations import mcp_store, service
from src.backend.integrations.errors import DuplicateNameError
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
