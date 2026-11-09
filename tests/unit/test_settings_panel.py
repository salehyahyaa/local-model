import pytest
from fastapi.testclient import TestClient

from src.backend import db
from src.backend.chat import system_prompt
from src.backend.integrations import service as integrations
from src.backend.main import app
from src.backend.settings_panel import connections

client = TestClient(app)
SECRET_TOKEN = "123:super-secret-token"


@pytest.fixture
def saved_prompt(monkeypatch):
    saved = {"value": None}

    async def read_saved():
        return saved["value"]

    async def save(text):
        saved["value"] = text

    monkeypatch.setattr(system_prompt, "read_saved", read_saved)
    monkeypatch.setattr(system_prompt, "save", save)
    return saved


def test_default_prompt_is_shown_when_nothing_is_saved(saved_prompt):
    body = client.get("/api/system-prompt").json()
    assert body["systemPrompt"] == system_prompt.DEFAULT_SYSTEM_PROMPT
    assert body["isDefault"] is True


def test_saving_and_restoring_the_prompt(saved_prompt):
    assert client.put("/api/system-prompt", json={"systemPrompt": "Be brief."}).json()["systemPrompt"] == "Be brief."
    assert saved_prompt["value"] == "Be brief."

    restored = client.put("/api/system-prompt", json={"systemPrompt": None}).json()
    assert restored["isDefault"] is True
    assert saved_prompt["value"] is None


def test_prompt_can_be_emptied(saved_prompt):
    body = client.put("/api/system-prompt", json={"systemPrompt": ""}).json()
    assert body["systemPrompt"] == ""
    assert body["isDefault"] is False


@pytest.mark.parametrize(
    "body", [[], {}, {"systemPrompt": 5}, {"systemPrompt": "x" * (system_prompt.MAX_LENGTH + 1)}]
)
def test_invalid_prompts_are_rejected(saved_prompt, body):
    assert client.put("/api/system-prompt", json=body).status_code == 422
    assert saved_prompt["value"] is None


def test_chat_falls_back_to_default_without_a_database(monkeypatch):
    monkeypatch.setattr(db, "pool", None)

    async def scenario():
        return await system_prompt.load_for_chat()

    import asyncio

    assert asyncio.run(scenario()) == system_prompt.DEFAULT_SYSTEM_PROMPT


@pytest.fixture
def telegram_on(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", SECRET_TOKEN)
    monkeypatch.setattr(connections.autostart, "is_running", lambda label: True)
    monkeypatch.setattr(connections.autostart, "LAUNCH_AGENTS_DIR", tmp_path)
    (tmp_path / f"{connections.TELEGRAM_LABEL}.plist").write_text("")


def by_name(items):
    return {item["name"]: item for item in items}


def test_connections_list_everything_and_never_a_secret(telegram_on, monkeypatch):
    async def fake_list():
        return {
            "mcpServers": [{"name": "Gmail", "target": "me@gmail.com", "enabled": True, "provider": "gmail"}],
            "apiIntegrations": [{"name": "Weather", "target": "https://w.example.com", "enabled": False}],
        }

    monkeypatch.setattr(integrations, "list_integrations", fake_list)
    response = client.get("/api/connections")

    assert SECRET_TOKEN not in response.text
    body = response.json()
    assert by_name(body["integrations"]) == {
        "Gmail": {"name": "Gmail", "detail": "me@gmail.com", "isConnected": True, "provider": "gmail"},
        "Weather": {"name": "Weather", "detail": "https://w.example.com", "isConnected": False, "provider": None},
    }
    services = by_name(body["services"])
    assert services["Telegram bot"] == {
        "name": "Telegram bot",
        "detail": "Running · starts at login",
        "isConnected": True,
    }
    assert services["Chat model"]["detail"] == "No model connected"
    assert set(services) == {
        "Chat model", "Telegram bot", "Voice input (Deepgram)", "Image generation", "Database", "App auto-start",
    }


def test_stopped_telegram_bot_shows_as_not_running(telegram_on, monkeypatch):
    monkeypatch.setattr(connections.autostart, "is_running", lambda label: False)
    status = connections.telegram_status()
    assert status["isConnected"] is False
    assert status["detail"].startswith("Not running")


def test_telegram_without_a_token_shows_not_set_up(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert connections.telegram_status() == {"name": "Telegram bot", "detail": "Not set up", "isConnected": False}


def test_connections_still_load_without_a_database(monkeypatch):
    monkeypatch.setattr(db, "pool", None)
    response = client.get("/api/connections")
    assert response.status_code == 200
    assert response.json()["integrations"] == []
    assert by_name(response.json()["services"])["Database"]["isConnected"] is False
