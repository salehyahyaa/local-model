import asyncio
import os

import pytest

from src.backend import config
from src.backend.integrations import api_store, mcp_store, service
from src.backend.integrations.errors import DuplicateNameError


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("")
    monkeypatch.setattr(config, "ENV_FILE", path)
    yield path
    for name in list(os.environ):
        if name.startswith("INTEGRATION_"):
            del os.environ[name]


@pytest.fixture
def fake_stores(monkeypatch):
    saved = {"mcp": [], "api": []}

    async def create_server(record):
        if any(server["name"] == record["name"] for server in saved["mcp"]):
            raise DuplicateNameError(record["name"])
        server = {"id": len(saved["mcp"]) + 1, "enabled": True, "headers": {}, "env": {}, "url": None,
                  "command": None, "args": [], **record}
        saved["mcp"].append(server)
        return server

    async def delete_server(server_id):
        for server in saved["mcp"]:
            if server["id"] == server_id:
                saved["mcp"].remove(server)
                return server
        return None

    async def create_integration(record):
        integration = {"id": len(saved["api"]) + 1, "enabled": True, **record}
        saved["api"].append(integration)
        return integration

    async def delete_integration(integration_id):
        for integration in saved["api"]:
            if integration["id"] == integration_id:
                saved["api"].remove(integration)
                return integration
        return None

    monkeypatch.setattr(mcp_store, "create_server", create_server)
    monkeypatch.setattr(mcp_store, "delete_server", delete_server)
    monkeypatch.setattr(api_store, "create_integration", create_integration)
    monkeypatch.setattr(api_store, "delete_integration", delete_integration)
    return saved


def stored_secrets():
    """With USE_KEYCHAIN=0 (tests/conftest.py) the secret store keeps secrets in the environment."""
    return {name: value for name, value in os.environ.items() if name.startswith("INTEGRATION_")}


def http_server(name="GitHub", api_key="ghp_secret"):
    return {"name": name, "transport": "http", "url": "https://mcp.example.com", "apiKey": api_key,
            "authHeader": "Authorization", "authPrefix": "Bearer "}


def test_api_key_goes_to_secret_store_not_database(env_file, fake_stores):
    created = asyncio.run(service.add_mcp_server(http_server()))
    assert created == {"id": 1, "kind": "mcp", "name": "GitHub", "transport": "http",
                       "target": "https://mcp.example.com", "enabled": True}
    assert fake_stores["mcp"][0]["headers"] == {"Authorization": "Bearer ${INTEGRATION_GITHUB_API_KEY}"}
    assert stored_secrets() == {"INTEGRATION_GITHUB_API_KEY": "ghp_secret"}


def test_stdio_environment_values_go_to_secret_store(env_file, fake_stores):
    server = {"name": "Files", "transport": "stdio", "command": "npx", "args": ["server"],
              "env": [{"name": "TOKEN", "value": "abc"}]}
    created = asyncio.run(service.add_mcp_server(server))
    assert created["target"] == "npx server"
    assert fake_stores["mcp"][0]["env"] == {"TOKEN": "${INTEGRATION_FILES_TOKEN}"}
    assert stored_secrets() == {"INTEGRATION_FILES_TOKEN": "abc"}


def test_no_api_key_means_no_headers(env_file, fake_stores):
    asyncio.run(service.add_mcp_server(http_server(api_key="")))
    assert fake_stores["mcp"][0]["headers"] == {}
    assert stored_secrets() == {}


def test_duplicate_name_is_rejected_and_keeps_original_secret(env_file, fake_stores):
    asyncio.run(service.add_mcp_server(http_server()))
    with pytest.raises(DuplicateNameError):
        asyncio.run(service.add_mcp_server(http_server(api_key="other")))
    assert stored_secrets() == {"INTEGRATION_GITHUB_API_KEY": "ghp_secret"}


def test_failed_save_removes_new_secrets(env_file, fake_stores, monkeypatch):
    async def broken_create(record):
        raise RuntimeError("database down")

    monkeypatch.setattr(mcp_store, "create_server", broken_create)
    with pytest.raises(RuntimeError):
        asyncio.run(service.add_mcp_server(http_server()))
    assert stored_secrets() == {}


def test_remove_deletes_secrets(env_file, fake_stores):
    asyncio.run(service.add_mcp_server(http_server()))
    assert asyncio.run(service.remove_mcp_server(1)) is True
    assert stored_secrets() == {}
    assert asyncio.run(service.remove_mcp_server(1)) is False


def test_api_integration_round_trip(env_file, fake_stores):
    integration = {"name": "Weather", "description": "Weather", "method": "GET", "url": "https://w.example.com",
                   "parameters": [], "apiKey": "w-key", "authHeader": "X-Api-Key", "authPrefix": ""}
    created = asyncio.run(service.add_api_integration(integration))
    assert created["kind"] == "api"
    assert fake_stores["api"][0]["headers"] == {"X-Api-Key": "${INTEGRATION_WEATHER_API_KEY}"}
    asyncio.run(service.remove_api_integration(created["id"]))
    assert stored_secrets() == {}


def test_username_and_password_become_basic_auth(env_file, fake_stores):
    server = {"name": "Jira", "transport": "http", "url": "https://mcp.example.com",
              "authType": "basic", "username": "saleh", "password": "pa:ss"}
    asyncio.run(service.add_mcp_server(server))
    assert fake_stores["mcp"][0]["headers"] == {"Authorization": "Basic ${INTEGRATION_JIRA_BASIC_AUTH}"}
    assert stored_secrets() == {"INTEGRATION_JIRA_BASIC_AUTH": "c2FsZWg6cGE6c3M="}
