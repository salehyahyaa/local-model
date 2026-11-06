"""Removed along with src/backend/models/openai_temporary."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from src.backend.chat import engine, model_slot
from src.backend.chat.model_slot import ModelError
from src.backend.main import app
from src.backend.models.openai_temporary import model as openai_temporary

MESSAGES = [{"role": "user", "content": "hi"}]
http_client = TestClient(app)


def stream_body(*chunks):
    lines = [f"data: {json.dumps(chunk)}" for chunk in chunks] + ["data: [DONE]"]
    return "\n\n".join(lines) + "\n\n"


def delta(**fields):
    return {"choices": [{"delta": fields}]}


def run_model(handler, tools=None):
    model = openai_temporary.OpenAITemporaryModel("secret-key", "test-model", transport=httpx.MockTransport(handler))

    async def collect():
        return [event async for event in model.stream(MESSAGES, tools or [])]

    return asyncio.run(collect())


def answer_with(*chunks):
    return lambda request: httpx.Response(200, text=stream_body(*chunks))


def test_text_is_streamed_in_pieces():
    events = run_model(answer_with(delta(content="Hel"), delta(content="lo"), {"choices": []}))
    assert events == [{"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}]


def test_split_tool_calls_are_put_back_together():
    first = {"index": 0, "id": "call1", "function": {"name": "Phone__call", "arguments": '{"a"'}}
    second = {"index": 1, "id": "call2", "function": {"name": "Other", "arguments": "{}"}}
    rest = {"index": 0, "function": {"arguments": ": 1}"}}
    events = run_model(answer_with(delta(tool_calls=[first, second]), delta(tool_calls=[rest])))
    assert events == [
        {"type": "tool_call", "id": "call1", "name": "Phone__call", "arguments": {"a": 1}},
        {"type": "tool_call", "id": "call2", "name": "Other", "arguments": {}},
    ]


def test_request_carries_the_model_key_and_tools():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=stream_body())

    tools = [{"type": "function", "function": {"name": "x"}}]
    run_model(handler, tools)
    assert seen["auth"] == "Bearer secret-key"
    assert seen["body"] == {"model": "test-model", "messages": MESSAGES, "stream": True, "tools": tools}


def test_empty_tool_list_is_left_out():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=stream_body())

    run_model(handler)
    assert "tools" not in seen["body"]


@pytest.mark.parametrize("arguments", ["{bad", "[1]"])
def test_unreadable_tool_arguments_are_an_error(arguments):
    part = {"index": 0, "id": "call1", "function": {"name": "x", "arguments": arguments}}
    with pytest.raises(ModelError):
        run_model(answer_with(delta(tool_calls=[part])))


def test_refused_request_is_an_error_without_the_key():
    with pytest.raises(ModelError) as error:
        run_model(lambda request: httpx.Response(401, json={"error": "bad key"}))
    assert "401" in str(error.value)
    assert "secret-key" not in str(error.value)


def test_unreachable_server_is_an_error():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ModelError):
        run_model(handler)


def test_unreadable_stream_is_an_error():
    with pytest.raises(ModelError):
        run_model(lambda request: httpx.Response(200, text="data: {bad\n\n"))


# Connecting


@pytest.fixture
def empty_slot(monkeypatch):
    monkeypatch.setattr(model_slot, "connected_model", None)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_connects_with_a_key_and_a_model_name(empty_slot, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    openai_temporary.connect()
    assert model_slot.connected_model.name == "test-model"


@pytest.mark.parametrize(("key", "name"), [("", "test-model"), ("secret-key", ""), ("secret-key", "   ")])
def test_stays_unconnected_when_either_setting_is_missing(empty_slot, monkeypatch, key, name):
    monkeypatch.setattr(openai_temporary, "get_secret", lambda secret: key)
    monkeypatch.setenv("OPENAI_MODEL", name)
    openai_temporary.connect()
    assert model_slot.connected_model is None


def test_model_list_reports_the_connected_model(monkeypatch):
    monkeypatch.setattr(model_slot, "connected_model", openai_temporary.OpenAITemporaryModel("key", "test-model"))
    assert http_client.get("/api/models").json() == {"models": ["test-model"], "defaultModel": "test-model"}


def test_model_list_is_empty_when_nothing_is_connected(monkeypatch):
    monkeypatch.setattr(model_slot, "connected_model", None)
    assert http_client.get("/api/models").json() == {"models": [], "defaultModel": None}


# Today's date


def test_model_is_told_the_date_and_offset():
    now = datetime(2026, 11, 6, 14, 3, tzinfo=timezone(timedelta(hours=-6)))
    message = engine.current_time_message(now)
    assert message["role"] == "system"
    assert "Friday, November 06, 2026, 14:03 (UTC-0600)" in message["content"]
