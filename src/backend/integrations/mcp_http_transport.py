import json
import logging

import httpx

from src.backend.integrations.errors import McpError

logger = logging.getLogger(__name__)


def parse_event_stream_lines(lines):
    data_lines = []
    for line in lines:
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
        elif line == "" and data_lines:
            yield json.loads("\n".join(data_lines))
            data_lines = []
    if data_lines:
        yield json.loads("\n".join(data_lines))


class McpHttpTransport:
    def __init__(self, url, headers, timeout):
        self.url = url
        self.headers = headers
        self.timeout = timeout
        self.client = None
        self.session_id = None
        self.protocol_version = None

    async def start(self):
        self.client = httpx.AsyncClient(timeout=self.timeout)

    def set_protocol_version(self, protocol_version):
        self.protocol_version = protocol_version

    def build_headers(self):
        headers = {
            **self.headers,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.protocol_version:
            headers["MCP-Protocol-Version"] = self.protocol_version
        return headers

    async def send_request(self, message):
        async with self.client.stream("POST", self.url, json=message, headers=self.build_headers()) as response:
            if response.status_code >= 400:
                await response.aread()
                raise McpError(f"Server answered HTTP {response.status_code}")
            self.session_id = response.headers.get("mcp-session-id", self.session_id)

            if response.headers.get("content-type", "").startswith("text/event-stream"):
                lines = [line async for line in response.aiter_lines()]
                for event in parse_event_stream_lines(lines):
                    if event.get("id") == message["id"]:
                        return event
                raise McpError("The server closed the stream without answering")

            await response.aread()
            return response.json()

    async def send_notification(self, message):
        response = await self.client.post(self.url, json=message, headers=self.build_headers())
        if response.status_code >= 400:
            raise McpError(f"Server answered HTTP {response.status_code}")

    async def close(self):
        if self.client is None:
            return
        if self.session_id:
            try:
                await self.client.delete(self.url, headers=self.build_headers())
            except httpx.HTTPError:
                logger.debug("Could not end MCP session at %s", self.url)
        await self.client.aclose()
        self.client = None
