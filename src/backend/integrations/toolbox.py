import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager

import httpx

from src.backend.config import MAX_TOOL_RESULT_CHARACTERS, TOOL_TIMEOUT
from src.backend.integrations import api_client, env_secrets
from src.backend.integrations.errors import McpError
from src.backend.integrations.mcp_client import McpSession
from src.backend.integrations.mcp_http_transport import McpHttpTransport
from src.backend.integrations.mcp_stdio_transport import McpStdioTransport

logger = logging.getLogger(__name__)

MAX_TOOL_NAME_LENGTH = 64
EMPTY_SCHEMA = {"type": "object", "properties": {}}


def make_tool_name(integration_name, action_name):
    raw_name = f"{integration_name}__{action_name}"
    return re.sub(r"[^A-Za-z0-9_]", "_", raw_name)[:MAX_TOOL_NAME_LENGTH]


def parameters_to_schema(parameters):
    properties = {
        parameter["name"]: {"type": "string", "description": parameter["description"]}
        for parameter in parameters
    }
    required = [parameter["name"] for parameter in parameters if parameter["required"]]
    return {"type": "object", "properties": properties, "required": required}


def create_transport(server):
    if server["transport"] == "http":
        headers = env_secrets.resolve_mapping(server["headers"])
        return McpHttpTransport(server["url"], headers, TOOL_TIMEOUT)
    environment = env_secrets.resolve_mapping(server["env"])
    return McpStdioTransport(server["command"], server["args"], environment, TOOL_TIMEOUT)


def truncate(text):
    if len(text) <= MAX_TOOL_RESULT_CHARACTERS:
        return text
    return text[:MAX_TOOL_RESULT_CHARACTERS] + "\n[result truncated]"


class Toolbox:
    def __init__(self):
        self.definitions = []
        self.tools = {}

    def has_tools(self):
        return bool(self.definitions)

    def add_tool(self, integration_name, action_name, description, schema, handler):
        tool_name = make_tool_name(integration_name, action_name)
        suffix = 2
        while tool_name in self.tools:
            tool_name = make_tool_name(integration_name, f"{action_name}_{suffix}")
            suffix += 1

        self.definitions.append(
            {
                "type": "function",
                "function": {"name": tool_name, "description": description, "parameters": schema or EMPTY_SCHEMA},
            }
        )
        self.tools[tool_name] = {"label": f"{integration_name} → {action_name}", "handler": handler}

    async def call(self, tool_name, arguments):
        tool = self.tools.get(tool_name)
        if tool is None:
            return tool_name, f"Error: there is no tool called {tool_name}."
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}

        logger.info("Running tool %s", tool["label"])
        try:
            result = await asyncio.wait_for(tool["handler"](arguments), TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            result = "Error: the tool took too long to answer."
        except (McpError, httpx.HTTPError, OSError) as error:
            logger.warning("Tool %s failed: %s", tool["label"], error)
            result = f"Error: {error}"
        return tool["label"], truncate(result)


def make_mcp_handler(session, tool_name):
    async def handler(arguments):
        return await session.call_tool(tool_name, arguments)

    return handler


def make_api_handler(integration):
    async def handler(arguments):
        return await api_client.call_api(integration, arguments, TOOL_TIMEOUT)

    return handler


async def open_mcp_session(server):
    session = McpSession(create_transport(server))
    try:
        await asyncio.wait_for(session.open(), TOOL_TIMEOUT)
        tools = await asyncio.wait_for(session.list_tools(), TOOL_TIMEOUT)
    except (McpError, httpx.HTTPError, OSError, asyncio.TimeoutError, ValueError) as error:
        logger.warning("Skipping MCP server %r: %s", server["name"], error)
        await session.close()
        return None, []
    logger.info("MCP server %r offers %d tool(s)", server["name"], len(tools))
    return session, tools


@asynccontextmanager
async def open_toolbox(mcp_servers, api_integrations):
    toolbox = Toolbox()
    opened_sessions = []
    try:
        results = await asyncio.gather(*(open_mcp_session(server) for server in mcp_servers))
        for server, (session, tools) in zip(mcp_servers, results):
            if session is None:
                continue
            opened_sessions.append(session)
            for tool in tools:
                toolbox.add_tool(
                    server["name"],
                    tool["name"],
                    tool.get("description", ""),
                    tool.get("inputSchema"),
                    make_mcp_handler(session, tool["name"]),
                )

        for integration in api_integrations:
            toolbox.add_tool(
                integration["name"],
                "call",
                integration["description"],
                parameters_to_schema(integration["parameters"]),
                make_api_handler(integration),
            )

        yield toolbox
    finally:
        for session in opened_sessions:
            await session.close()
