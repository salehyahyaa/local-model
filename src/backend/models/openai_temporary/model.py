"""Temporary: lets the owner test the app on OpenAI until their own model is ready. See README.md for removing it."""

import json
import logging
import os

import httpx

from src.backend import config  # noqa: F401  (importing it loads .env, which OPENAI_MODEL may be set in)
from src.backend.chat import model_slot
from src.backend.chat.model_slot import ModelError
from src.backend.secret_store import get_secret

logger = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1"
TIMEOUT = httpx.Timeout(120, connect=10)
DATA_PREFIX = "data:"
END_OF_STREAM = "[DONE]"
UNREADABLE_TOOL_CALL = "OpenAI sent a tool call that couldn't be read."


def read_line(line):
    """Returns the chunk on one line of the stream, or None for blank lines and the end marker."""
    if not line.startswith(DATA_PREFIX):
        return None
    data = line[len(DATA_PREFIX) :].strip()
    if data == END_OF_STREAM:
        return None
    try:
        return json.loads(data)
    except ValueError as error:
        raise ModelError("OpenAI sent an answer that couldn't be read.") from error


def add_tool_call_parts(calls, parts):
    """OpenAI splits each tool call across chunks, matched up by index."""
    for part in parts:
        call = calls.setdefault(part.get("index", 0), {"id": "", "name": "", "arguments": ""})
        function = part.get("function") or {}
        call["id"] += part.get("id") or ""
        call["name"] += function.get("name") or ""
        call["arguments"] += function.get("arguments") or ""


def finished_tool_call(call):
    try:
        arguments = json.loads(call["arguments"] or "{}")
    except ValueError as error:
        raise ModelError(UNREADABLE_TOOL_CALL) from error
    if not isinstance(arguments, dict):
        raise ModelError(UNREADABLE_TOOL_CALL)
    return {"type": "tool_call", "id": call["id"], "name": call["name"], "arguments": arguments}


class OpenAITemporaryModel:
    def __init__(self, api_key, name, transport=None):
        self.api_key = api_key
        self.name = name
        self.transport = transport

    async def stream(self, messages, tools):
        body = {"model": self.name, "messages": messages, "stream": True}
        if tools:
            body["tools"] = tools
        headers = {"Authorization": f"Bearer {self.api_key}"}
        calls = {}
        try:
            async with httpx.AsyncClient(base_url=API_URL, timeout=TIMEOUT, transport=self.transport) as client:
                async with client.stream("POST", "/chat/completions", json=body, headers=headers) as response:
                    if response.is_error:
                        raise ModelError(f"OpenAI refused the request (HTTP {response.status_code}).")
                    async for line in response.aiter_lines():
                        chunk = read_line(line)
                        choices = chunk.get("choices") if isinstance(chunk, dict) else None
                        if not choices:
                            continue
                        delta = choices[0].get("delta") or {}
                        if delta.get("content"):
                            yield {"type": "text", "text": delta["content"]}
                        add_tool_call_parts(calls, delta.get("tool_calls") or [])
        except httpx.HTTPError as error:
            raise ModelError("Couldn't reach OpenAI.") from error

        for index in sorted(calls):
            yield finished_tool_call(calls[index])


def connect():
    """Only connects once the owner has set both the key and the model name. There is no default model."""
    api_key = get_secret("OPENAI_API_KEY")
    name = os.getenv("OPENAI_MODEL", "").strip()
    if api_key and name:
        model_slot.connected_model = OpenAITemporaryModel(api_key, name)
        logger.info("Connected the temporary OpenAI model %s", name)
