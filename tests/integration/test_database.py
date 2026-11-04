import asyncio
import os

import pytest
from dotenv import dotenv_values
from fastapi.testclient import TestClient

from src.backend import config, db, store
from src.backend.models.image_generation import store as image_store
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


def run_with_database(database_url, monkeypatch, scenario):
    monkeypatch.setattr(db, "DATABASE_URL", database_url)

    async def run():
        await db.connect()
        try:
            return await scenario()
        finally:
            await db.disconnect()

    return asyncio.run(run())


def test_conversations_and_messages(test_database_url, monkeypatch):
    async def scenario():
        conversation = await store.create_conversation()
        await store.add_message(conversation["id"], "user", "hello", "image-generation")
        await store.add_message(conversation["id"], "assistant", "hi there", "image-generation")
        await store.update_conversation(conversation["id"], {"title": "Greeting", "isPinned": True})
        await store.delete_last_message(conversation["id"])
        return await store.get_state()

    state = run_with_database(test_database_url, monkeypatch, scenario)
    conversation = state["conversations"][0]
    assert conversation["title"] == "Greeting"
    assert conversation["isPinned"] is True
    assert conversation["messages"] == [
        {"role": "user", "content": "hello", "model": "image-generation", "imageFiles": []}
    ]


def test_image_exchange_is_saved_in_order(test_database_url, monkeypatch):
    async def scenario():
        conversation = await store.create_conversation()
        missing = await image_store.save_exchange(conversation["id"] + 1000, "a cat", [], ["out.png"])
        await image_store.save_exchange(conversation["id"], "a cat", ["a.png", "b.png"], ["c.png", "d.png"])
        files = await image_store.files_in_conversation(conversation["id"])
        return missing, files, await store.get_state()

    missing, files, state = run_with_database(test_database_url, monkeypatch, scenario)
    assert missing is None
    assert sorted(files) == ["a.png", "b.png", "c.png", "d.png"]
    assert state["conversations"][0]["messages"] == [
        {"role": "user", "content": "a cat", "model": "image-generation", "imageFiles": ["a.png", "b.png"]},
        {"role": "assistant", "content": "", "model": "image-generation", "imageFiles": ["c.png", "d.png"]},
    ]


def test_mcp_server_store(test_database_url, monkeypatch):
    async def scenario():
        created = await mcp_store.create_server(
            {"name": "Files", "transport": "stdio", "command": "npx", "args": ["server"],
             "env": {"TOKEN": "${INTEGRATION_FILES_TOKEN}"}}
        )
        with pytest.raises(DuplicateNameError):
            await mcp_store.create_server({"name": "Files", "transport": "stdio", "command": "npx"})
        await mcp_store.set_enabled(created["id"], False)
        enabled_servers = await mcp_store.list_enabled_servers()
        all_servers = await mcp_store.list_servers()
        deleted = await mcp_store.delete_server(created["id"])
        return created, enabled_servers, all_servers, deleted, await mcp_store.list_servers()

    created, enabled_servers, all_servers, deleted, remaining = run_with_database(
        test_database_url, monkeypatch, scenario
    )
    assert created["args"] == ["server"]
    assert created["env"] == {"TOKEN": "${INTEGRATION_FILES_TOKEN}"}
    assert enabled_servers == []
    assert all_servers[0]["enabled"] is False
    assert deleted["name"] == "Files"
    assert remaining == []


def test_api_integration_store(test_database_url, monkeypatch):
    async def scenario():
        created = await api_store.create_integration(
            {"name": "Weather", "description": "Weather", "method": "GET", "url": "https://w.example.com/{city}",
             "parameters": [{"name": "city", "description": "", "required": True}],
             "headers": {"X-Api-Key": "${INTEGRATION_WEATHER_API_KEY}"}}
        )
        return created, await api_store.list_enabled_integrations()

    created, enabled = run_with_database(test_database_url, monkeypatch, scenario)
    assert created["parameters"] == [{"name": "city", "description": "", "required": True}]
    assert enabled == [created]


def test_service_keeps_keys_out_of_the_database(test_database_url, monkeypatch, env_file):
    async def scenario():
        await service.add_mcp_server(
            {"name": "GitHub", "transport": "http", "url": "https://mcp.example.com", "apiKey": "ghp_secret",
             "authHeader": "Authorization", "authPrefix": "Bearer "}
        )
        async with db.pool.acquire() as connection:
            stored_headers = await connection.fetchval("SELECT headers::text FROM mcp_servers")
        listing = await service.list_integrations()
        await service.remove_mcp_server(listing["mcpServers"][0]["id"])
        return stored_headers, listing

    stored_headers, listing = run_with_database(test_database_url, monkeypatch, scenario)
    assert "ghp_secret" not in stored_headers
    assert "${INTEGRATION_GITHUB_API_KEY}" in stored_headers
    assert listing["mcpServers"][0]["name"] == "GitHub"
    assert dotenv_values(env_file) == {}


def test_integration_api_end_to_end(test_database_url, monkeypatch, env_file):
    monkeypatch.setattr(db, "DATABASE_URL", test_database_url)
    from src.backend.main import app

    with TestClient(app) as client:
        response = client.post(
            "/api/integrations/api",
            json={"name": "Weather", "description": "Gets weather", "method": "GET",
                  "url": "https://w.example.com/{city}",
                  "parameters": [{"name": "city", "description": "City", "required": True}],
                  "apiKey": "w-key", "authHeader": "X-Api-Key", "authPrefix": ""},
        )
        assert response.status_code == 201
        integration_id = response.json()["id"]
        assert dotenv_values(env_file) == {"INTEGRATION_WEATHER_API_KEY": "w-key"}

        assert client.post("/api/integrations/api", json={
            "name": "Weather", "description": "Again", "method": "GET", "url": "https://w.example.com"
        }).status_code == 409

        assert client.patch(f"/api/integrations/api/{integration_id}", json={"enabled": False}).status_code == 200
        listing = client.get("/api/integrations").json()
        assert listing["apiIntegrations"][0]["enabled"] is False

        assert client.delete(f"/api/integrations/api/{integration_id}").status_code == 200
        assert client.get("/api/integrations").json() == {"mcpServers": [], "apiIntegrations": []}
        assert dotenv_values(env_file) == {}
