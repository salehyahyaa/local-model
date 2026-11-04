import asyncio

import pytest

from src.backend.integrations.errors import McpError
from src.backend.integrations.mcp_client import McpSession, format_tool_result


class FakeTransport:
    def __init__(self, responses):
        self.responses = responses
        self.sent_requests = []
        self.sent_notifications = []
        self.protocol_version = None
        self.started = False
        self.closed = False

    async def start(self):
        self.started = True

    def set_protocol_version(self, protocol_version):
        self.protocol_version = protocol_version

    async def send_request(self, message):
        self.sent_requests.append(message)
        return {"jsonrpc": "2.0", "id": message["id"], **self.responses[message["method"]].pop(0)}

    async def send_notification(self, message):
        self.sent_notifications.append(message)

    async def close(self):
        self.closed = True


def test_open_initializes_and_sends_initialized_notification():
    transport = FakeTransport({"initialize": [{"result": {"protocolVersion": "2025-03-26"}}]})
    asyncio.run(McpSession(transport).open())
    assert transport.started
    assert transport.sent_requests[0]["method"] == "initialize"
    assert transport.protocol_version == "2025-03-26"
    assert transport.sent_notifications == [{"jsonrpc": "2.0", "method": "notifications/initialized"}]


def test_list_tools_follows_pagination():
    transport = FakeTransport(
        {
            "tools/list": [
                {"result": {"tools": [{"name": "first"}], "nextCursor": "page-2"}},
                {"result": {"tools": [{"name": "second"}]}},
            ]
        }
    )
    tools = asyncio.run(McpSession(transport).list_tools())
    assert [tool["name"] for tool in tools] == ["first", "second"]
    assert transport.sent_requests[1]["params"] == {"cursor": "page-2"}


def test_call_tool_returns_text():
    transport = FakeTransport({"tools/call": [{"result": {"content": [{"type": "text", "text": "42"}]}}]})
    result = asyncio.run(McpSession(transport).call_tool("add", {"a": 40, "b": 2}))
    assert result == "42"
    assert transport.sent_requests[0]["params"] == {"name": "add", "arguments": {"a": 40, "b": 2}}


def test_request_ids_increase():
    transport = FakeTransport({"tools/list": [{"result": {"tools": []}}, {"result": {"tools": []}}]})
    session = McpSession(transport)
    asyncio.run(session.list_tools())
    asyncio.run(session.list_tools())
    assert [request["id"] for request in transport.sent_requests] == [1, 2]


def test_error_response_raises():
    transport = FakeTransport({"tools/call": [{"error": {"code": -32602, "message": "Unknown tool"}}]})
    with pytest.raises(McpError, match="Unknown tool"):
        asyncio.run(McpSession(transport).call_tool("missing", {}))


def test_format_tool_result_variants():
    assert format_tool_result({"content": [{"type": "text", "text": "a"}, {"type": "image"}]}) == (
        "a\n[image content omitted]"
    )
    assert format_tool_result({"content": [{"type": "text", "text": "bad"}], "isError": True}) == "Error: bad"
    assert format_tool_result({"structuredContent": {"value": 1}}) == '{"value": 1}'
