import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager

import httpx

from src.backend.config import MAX_TOOL_RESULT_CHARACTERS, TOOL_TIMEOUT
from src.backend.integrations import api_client, env_secrets, oauth
from src.backend.integrations.errors import McpError
from src.backend.integrations.mcp_client import McpSession
from src.backend.integrations.mcp_http_transport import McpHttpTransport
from src.backend.integrations.mcp_stdio_transport import McpStdioTransport

logger = logging.getLogger(__name__)

MAX_TOOL_NAME_LENGTH = 64
EMPTY_SCHEMA = {"type": "object", "properties": {}}
# Longer than a normal call: the first run of a local server often has to download it.
CONNECTION_CHECK_TIMEOUT = 120


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


def create_transport(server, timeout=TOOL_TIMEOUT):
    if server["transport"] == "http":
        headers = env_secrets.resolve_mapping(server["headers"])
        return McpHttpTransport(server["url"], headers, timeout)
    environment = env_secrets.resolve_mapping(server["env"])
    return McpStdioTransport(server["command"], server["args"], environment, timeout)


async def check_connection(server):
    """Connects to a server being added, so a wrong address or login fails on the form and not later in a chat."""
    session = McpSession(create_transport(server, CONNECTION_CHECK_TIMEOUT))
    try:
        await asyncio.wait_for(session.open(), CONNECTION_CHECK_TIMEOUT)
        await asyncio.wait_for(session.list_tools(), CONNECTION_CHECK_TIMEOUT)
    except asyncio.TimeoutError as error:
        raise McpError("The server didn't answer in time.") from error
    except (httpx.HTTPError, OSError, ValueError) as error:
        raise McpError(str(error) or "Couldn't reach the server.") from error
    finally:
        await session.close()


def is_error_result(result):
    """Every way a tool can fail comes back as text starting with "Error:"."""
    return isinstance(result, str) and result.startswith("Error:")


def truncate(text):
    if len(text) <= MAX_TOOL_RESULT_CHARACTERS:
        return text
    return text[:MAX_TOOL_RESULT_CHARACTERS] + "\n[result truncated]"


def read_arguments(arguments):
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
    return arguments if isinstance(arguments, dict) else {}


class Toolbox:
    def __init__(self):
        self.definitions = []
        self.tools = {}

    def has_tools(self):
        return bool(self.definitions)

    def needs_approval(self, tool_name):
        tool = self.tools.get(tool_name)
        return tool is not None and tool["requiresApproval"]

    def label_for(self, tool_name):
        tool = self.tools.get(tool_name)
        return tool["label"] if tool else tool_name

    def add_tool(self, integration_name, action_name, description, schema, handler, requires_approval=True):
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
        self.tools[tool_name] = {
            "label": f"{integration_name} → {action_name}",
            "handler": handler,
            "requiresApproval": requires_approval,
        }

    async def call(self, tool_name, arguments):
        tool = self.tools.get(tool_name)
        if tool is None:
            return tool_name, f"Error: there is no tool called {tool_name}."
        arguments = read_arguments(arguments)

        logger.info("Running tool %s", tool["label"])
        try:
            result = await asyncio.wait_for(tool["handler"](arguments), TOOL_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("Tool %s timed out", tool["label"])
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
    try:
        await asyncio.wait_for(oauth.refresh_if_needed(server), TOOL_TIMEOUT)
    except (McpError, asyncio.TimeoutError) as error:
        logger.warning("Skipping MCP server %r: %s", server["name"], error)
        return None, []
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
                    # Only tools that declare themselves read-only skip the owner's approval.
                    requires_approval=(tool.get("annotations") or {}).get("readOnlyHint") is not True,
                )

        for integration in api_integrations:
            toolbox.add_tool(
                integration["name"],
                "call",
                integration["description"],
                parameters_to_schema(integration["parameters"]),
                make_api_handler(integration),
                requires_approval=integration["method"] != "GET",
            )

        yield toolbox
    finally:
        for session in opened_sessions:
            await session.close()
