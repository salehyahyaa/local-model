import asyncio
import sys
from pathlib import Path

from src.backend.integrations.toolbox import open_toolbox

FAKE_STDIO_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "fake_mcp_stdio_server.py"


def run_with_toolbox(mcp_servers, scenario):
    async def run():
        async with open_toolbox(mcp_servers, []) as toolbox:
            return await scenario(toolbox)

    return asyncio.run(run())


def test_stdio_server_lists_and_calls_tools(monkeypatch):
    monkeypatch.setenv("INTEGRATION_FAKE_TOKEN", "from-env-file")
    server = {
        "name": "Fake",
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(FAKE_STDIO_SERVER)],
        "env": {"TOKEN": "${INTEGRATION_FAKE_TOKEN}"},
    }

    async def scenario(toolbox):
        names = [definition["function"]["name"] for definition in toolbox.definitions]
        added = await toolbox.call("Fake__add", {"a": 2, "b": 3})
        token = await toolbox.call("Fake__read_token", {})
        return names, added, token

    names, added, token = run_with_toolbox([server], scenario)
    assert names == ["Fake__add", "Fake__read_token"]
    assert added == ("Fake → add", "5")
    assert token == ("Fake → read_token", "from-env-file")


def test_http_server_lists_and_calls_tools(fake_http_services, monkeypatch):
    monkeypatch.setenv("INTEGRATION_REMOTE_API_KEY", "test-token")
    server = {
        "name": "Remote",
        "transport": "http",
        "url": f"{fake_http_services}/mcp",
        "headers": {"Authorization": "Bearer ${INTEGRATION_REMOTE_API_KEY}"},
    }

    async def scenario(toolbox):
        names = [definition["function"]["name"] for definition in toolbox.definitions]
        return names, await toolbox.call("Remote__echo", {"text": "hello"})

    names, result = run_with_toolbox([server], scenario)
    assert names == ["Remote__echo"]
    assert result == ("Remote → echo", "hello")


def test_http_server_with_wrong_key_is_skipped(fake_http_services, monkeypatch):
    monkeypatch.setenv("INTEGRATION_REMOTE_API_KEY", "wrong")
    server = {
        "name": "Remote",
        "transport": "http",
        "url": f"{fake_http_services}/mcp",
        "headers": {"Authorization": "Bearer ${INTEGRATION_REMOTE_API_KEY}"},
    }

    async def scenario(toolbox):
        return toolbox.has_tools()

    assert run_with_toolbox([server], scenario) is False
