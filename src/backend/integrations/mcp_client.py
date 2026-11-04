import json

from src.backend.integrations.errors import McpError

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "local-model", "version": "0.1.0"}


def format_tool_result(result):
    parts = []
    for item in result.get("content", []):
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
        elif item.get("type") == "resource":
            parts.append(item.get("resource", {}).get("text", "[resource]"))
        else:
            parts.append(f"[{item.get('type', 'unknown')} content omitted]")
    if not parts and "structuredContent" in result:
        parts.append(json.dumps(result["structuredContent"]))
    text = "\n".join(parts)
    if result.get("isError"):
        return f"Error: {text}"
    return text


class McpSession:
    def __init__(self, transport):
        self.transport = transport
        self.next_request_id = 1

    async def request(self, method, params=None):
        message = {"jsonrpc": "2.0", "id": self.next_request_id, "method": method}
        if params is not None:
            message["params"] = params
        self.next_request_id += 1

        response = await self.transport.send_request(message)
        if "error" in response:
            raise McpError(response["error"].get("message", "Unknown MCP error"))
        return response.get("result", {})

    async def open(self):
        await self.transport.start()
        result = await self.request(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
        )
        self.transport.set_protocol_version(result.get("protocolVersion", PROTOCOL_VERSION))
        await self.transport.send_notification({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def list_tools(self):
        tools = []
        cursor = None
        while True:
            result = await self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(result.get("tools", []))
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    async def call_tool(self, tool_name, arguments):
        result = await self.request("tools/call", {"name": tool_name, "arguments": arguments})
        return format_tool_result(result)

    async def close(self):
        await self.transport.close()
