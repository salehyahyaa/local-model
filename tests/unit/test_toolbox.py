import asyncio

from src.backend.integrations import toolbox as toolbox_module
from src.backend.integrations.errors import McpError
from src.backend.integrations.toolbox import Toolbox, make_tool_name, open_toolbox, parameters_to_schema


def test_make_tool_name_is_safe_and_short():
    assert make_tool_name("My GitHub", "search-issues") == "My_GitHub__search_issues"
    assert len(make_tool_name("x" * 100, "y")) == 64


def test_parameters_to_schema():
    schema = parameters_to_schema(
        [{"name": "city", "description": "City", "required": True}, {"name": "units", "description": "", "required": False}]
    )
    assert schema == {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "City"}, "units": {"type": "string", "description": ""}},
        "required": ["city"],
    }


def test_duplicate_tool_names_get_a_suffix():
    toolbox = Toolbox()

    async def handler(arguments):
        return "ok"

    toolbox.add_tool("Svc", "run", "", None, handler)
    toolbox.add_tool("Svc", "run", "", None, handler)
    assert [definition["function"]["name"] for definition in toolbox.definitions] == ["Svc__run", "Svc__run_2"]


def test_call_parses_string_arguments_and_returns_label():
    toolbox = Toolbox()
    received = []

    async def handler(arguments):
        received.append(arguments)
        return "done"

    toolbox.add_tool("Svc", "run", "Runs it", None, handler)
    label, result = asyncio.run(toolbox.call("Svc__run", '{"x": 1}'))
    assert (label, result) == ("Svc → run", "done")
    assert received == [{"x": 1}]


def test_call_turns_tool_errors_into_text():
    toolbox = Toolbox()

    async def handler(arguments):
        raise McpError("server exploded")

    toolbox.add_tool("Svc", "run", "", None, handler)
    _, result = asyncio.run(toolbox.call("Svc__run", {}))
    assert result == "Error: server exploded"


def test_call_unknown_tool():
    _, result = asyncio.run(Toolbox().call("nope", {}))
    assert "no tool called nope" in result


def test_long_results_are_truncated(monkeypatch):
    monkeypatch.setattr(toolbox_module, "MAX_TOOL_RESULT_CHARACTERS", 10)
    toolbox = Toolbox()

    async def handler(arguments):
        return "a" * 50

    toolbox.add_tool("Svc", "run", "", None, handler)
    _, result = asyncio.run(toolbox.call("Svc__run", {}))
    assert result == "a" * 10 + "\n[result truncated]"


def test_open_toolbox_adds_api_integrations():
    integration = {
        "name": "Weather",
        "description": "Gets weather",
        "method": "GET",
        "url": "https://api.example.com",
        "parameters": [],
        "headers": {},
    }

    async def scenario():
        async with open_toolbox([], [integration]) as toolbox:
            return toolbox.definitions

    definitions = asyncio.run(scenario())
    assert definitions[0]["function"]["name"] == "Weather__call"
    assert definitions[0]["function"]["description"] == "Gets weather"


def test_open_toolbox_skips_unreachable_mcp_servers():
    server = {"name": "Broken", "transport": "stdio", "command": "/definitely/not/a/command", "args": [], "env": {}}

    async def scenario():
        async with open_toolbox([server], []) as toolbox:
            return toolbox.has_tools()

    assert asyncio.run(scenario()) is False
