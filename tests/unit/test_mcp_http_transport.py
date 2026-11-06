import asyncio
import json

import httpx
import pytest

from src.backend.integrations.errors import McpError
from src.backend.integrations.mcp_http_transport import McpHttpTransport, read_event_stream


def make_transport(handler):
    transport = McpHttpTransport("https://mcp.example.com/mcp", {"Authorization": "Bearer abc"}, 5)
    transport.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return transport


def test_read_event_stream():
    async def lines():
        for line in ["event: message", 'data: {"id": 1}', "", 'data: {"id": 2,', 'data: "ok": true}', ""]:
            yield line

    async def scenario():
        return [event async for event in read_event_stream(lines())]

    assert asyncio.run(scenario()) == [{"id": 1}, {"id": 2, "ok": True}]


def test_answer_is_returned_even_if_the_server_keeps_the_stream_open():
    class EndlessStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}\n\n'
            await asyncio.Event().wait()

    def handler(request):
        return httpx.Response(200, stream=EndlessStream(), headers={"Content-Type": "text/event-stream"})

    transport = make_transport(handler)
    message = {"jsonrpc": "2.0", "id": 7, "method": "tools/list"}
    response = asyncio.run(asyncio.wait_for(transport.send_request(message), 2))
    assert response["result"] == {"tools": []}


def test_json_response_and_session_header():
    seen_headers = []

    def handler(request):
        seen_headers.append(dict(request.headers))
        body = json.loads(request.content)
        return httpx.Response(
            200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}}, headers={"Mcp-Session-Id": "session-1"}
        )

    transport = make_transport(handler)

    async def scenario():
        await transport.send_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        transport.set_protocol_version("2025-06-18")
        await transport.send_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    asyncio.run(scenario())
    assert seen_headers[0]["authorization"] == "Bearer abc"
    assert "mcp-session-id" not in seen_headers[0]
    assert seen_headers[1]["mcp-session-id"] == "session-1"
    assert seen_headers[1]["mcp-protocol-version"] == "2025-06-18"


def test_event_stream_response_picks_matching_id():
    def handler(request):
        stream = 'data: {"jsonrpc": "2.0", "method": "notifications/progress"}\n\n'
        stream += 'data: {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}\n\n'
        return httpx.Response(200, text=stream, headers={"Content-Type": "text/event-stream"})

    transport = make_transport(handler)
    response = asyncio.run(transport.send_request({"jsonrpc": "2.0", "id": 7, "method": "tools/list"}))
    assert response["result"] == {"tools": []}


def test_http_error_raises():
    transport = make_transport(lambda request: httpx.Response(401, text="no"))
    with pytest.raises(McpError, match="401"):
        asyncio.run(transport.send_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"}))
