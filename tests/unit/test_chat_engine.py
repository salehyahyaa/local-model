"""The chat loop, driven by a fake model. No real model is involved."""

import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from src.backend.chat import approvals, engine, model_slot, system_prompt
from src.backend.chat.model_slot import ModelError
from src.backend.integrations import service, toolbox
from src.backend.integrations.toolbox import Toolbox
from src.backend.main import app

client = TestClient(app)
USER_MESSAGE = [{"role": "user", "content": "email amy"}]
SEND_ARGUMENTS = {"to": "amy@example.com", "subject": "Hi", "body": "Hello"}


def tool_call(name, arguments=None):
    return {"type": "tool_call", "id": f"call_{name}", "name": name, "arguments": arguments or {}}


class FakeModel:
    """Plays back one list of events per round and records what it was given."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.seen_messages = []
        self.seen_tools = []

    async def stream(self, messages, tools):
        self.seen_messages.append(list(messages))
        self.seen_tools.append(tools)
        for event in self.rounds.pop(0):
            if isinstance(event, Exception):
                raise event
            yield event


@pytest.fixture
def tools(monkeypatch):
    """A toolbox with one ordinary tool and one that needs approval; records which of them ran."""
    box = Toolbox()
    ran = []

    def make_handler(name):
        async def handler(arguments):
            ran.append((name, arguments))
            return f"{name} done"

        return handler

    box.add_tool("Gmail", "search_email", "Search", None, make_handler("search"), requires_approval=False)
    box.add_tool("Gmail", "send_email", "Send", None, make_handler("send"))

    @asynccontextmanager
    async def fake_open_toolbox(mcp_servers, api_integrations):
        yield box

    async def no_integrations():
        return [], []

    monkeypatch.setattr(engine, "open_toolbox", fake_open_toolbox)
    monkeypatch.setattr(service, "load_enabled_integrations", no_integrations)
    return ran


async def collect(events, answer=None):
    collected = []
    async for event in events:
        collected.append(event)
        if event["type"] == "approval" and answer is not None:
            assert approvals.resolve(event["id"], answer)
    return collected


def run(model, can_approve=True, answer=None):
    return asyncio.run(collect(engine.run_chat(USER_MESSAGE, model, can_approve), answer))


def tool_results(model):
    return [message["content"] for message in model.seen_messages[-1] if message["role"] == "tool"]


def test_model_is_told_what_is_connected_without_any_secrets():
    gmail = {
        "id": 1,
        "name": "Gmail",
        "transport": "stdio",
        "args": service.GMAIL_SERVER_ARGS,
        "env": {"GMAIL_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "secret-password"},
        "enabled": True,
    }
    calendar = {
        "id": 2,
        "name": "Google Calendar",
        "transport": "stdio",
        "args": service.GOOGLE_CALENDAR_SERVER_ARGS,
        "env": {"GOOGLE_ACCOUNT": "me@gmail.com", "GOOGLE_CLIENT_ID": "secret-id"},
        "enabled": True,
    }
    other = {
        "id": 3,
        "name": "Notes",
        "transport": "http",
        "url": "https://user@notes.example.com/?key=secret-key",
        "args": [],
        "enabled": True,
    }
    weather = {"name": "Weather", "url": "https://w.example.com/?key=secret-key"}

    messages = engine.connections_messages([gmail, calendar, other], [weather])

    assert messages == [
        {
            "role": "system",
            "content": (
                "The owner's connected services: Gmail (me@gmail.com), Google Calendar (me@gmail.com), Notes, Weather."
            ),
        }
    ]


def test_nothing_connected_adds_no_message():
    assert engine.connections_messages([], []) == []


def test_plain_reply_streams_text(tools):
    events = run(FakeModel([{"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}]))
    assert events == [{"type": "text", "text": "Hel"}, {"type": "text", "text": "lo"}]


def test_model_is_told_to_use_tools_only_when_asked(tools):
    model = FakeModel([])
    run(model)
    assert model.seen_messages[0][0] == {"role": "system", "content": system_prompt.DEFAULT_SYSTEM_PROMPT}
    assert "current date and time" in model.seen_messages[0][1]["content"]
    assert model.seen_messages[0][2:] == USER_MESSAGE


def use_saved_prompt(monkeypatch, saved):
    async def read_saved():
        return saved

    monkeypatch.setattr(system_prompt, "read_saved", read_saved)


def test_model_gets_the_prompt_the_owner_saved(tools, monkeypatch):
    use_saved_prompt(monkeypatch, "Be brief.")
    model = FakeModel([])
    run(model)
    assert model.seen_messages[0][0] == {"role": "system", "content": "Be brief."}


def test_cleared_prompt_sends_only_the_date_and_keeps_approval(tools, monkeypatch):
    use_saved_prompt(monkeypatch, "")
    model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS)], [])

    run(model, answer=False)

    assert "current date and time" in model.seen_messages[0][0]["content"]
    assert model.seen_messages[0][1:] == USER_MESSAGE
    assert tools == []


def test_only_read_only_api_calls_skip_approval():
    def api(name, method):
        return {"name": name, "description": "x", "method": method, "url": "https://x.example.com",
                "parameters": [], "headers": {}}

    async def scenario():
        integrations = [api("Read", "GET"), api("Order", "POST"), api("Remove", "DELETE")]
        async with toolbox.open_toolbox([], integrations) as box:
            return {name: box.needs_approval(name) for name in box.tools}

    assert asyncio.run(scenario()) == {"Read__call": False, "Order__call": True, "Remove__call": True}


def test_enabled_tools_are_offered_to_the_model(tools):
    model = FakeModel([])
    run(model)
    names = [definition["function"]["name"] for definition in model.seen_tools[0]]
    assert names == ["Gmail__search_email", "Gmail__send_email"]


def test_ordinary_tool_runs_and_the_result_goes_back_to_the_model(tools):
    model = FakeModel(
        [tool_call("Gmail__search_email", {"query": "is:unread"})],
        [{"type": "text", "text": "You have mail"}],
    )

    events = run(model)

    assert tools == [("search", {"query": "is:unread"})]
    assert events == [{"type": "tool", "label": "Gmail → search_email"}, {"type": "text", "text": "You have mail"}]
    assert tool_results(model) == ["search done"]
    assistant = next(message for message in model.seen_messages[-1] if message["role"] == "assistant")
    assert assistant["tool_calls"][0]["function"] == {
        "name": "Gmail__search_email",
        "arguments": json.dumps({"query": "is:unread"}),
    }


def test_send_shows_exactly_what_will_go_out_and_runs_after_approval(tools):
    model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS)], [{"type": "text", "text": "Sent"}])

    events = run(model, answer=True)

    assert events[0]["type"] == "approval"
    assert events[0]["label"] == "Gmail → send_email"
    assert events[0]["details"] == SEND_ARGUMENTS
    assert tools == [("send", SEND_ARGUMENTS)]
    assert events[1:] == [{"type": "tool", "label": "Gmail → send_email"}, {"type": "text", "text": "Sent"}]


def test_nothing_runs_while_waiting_for_approval(tools):
    async def scenario():
        model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS)], [])
        events = engine.run_chat(USER_MESSAGE, model, True)
        approval = await anext(events)
        waiting = asyncio.ensure_future(anext(events, None))
        await asyncio.sleep(0.01)
        assert tools == []
        assert not waiting.done()
        approvals.resolve(approval["id"], False)
        await waiting
        await events.aclose()

    asyncio.run(scenario())


def test_denied_send_never_runs_and_the_model_is_told(tools):
    model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS)], [{"type": "text", "text": "OK"}])

    events = run(model, answer=False)

    assert tools == []
    assert tool_results(model) == [engine.NOT_APPROVED]
    assert events[-1] == {"type": "text", "text": "OK"}


def test_no_answer_in_time_counts_as_denied(tools, monkeypatch):
    monkeypatch.setattr(approvals, "APPROVAL_TIMEOUT", 0.01)
    model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS)], [])

    run(model)

    assert tools == []
    assert tool_results(model) == [engine.NOT_APPROVED]
    assert approvals.pending == {}


def test_clients_that_cannot_approve_never_send(tools):
    """Telegram can't show the approval card, so it must not wait for one or send anything."""
    model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS)], [])

    events = run(model, can_approve=False)

    assert tools == []
    assert events == []
    assert tool_results(model) == [engine.CANNOT_APPROVE_HERE]


def test_model_cannot_loop_forever(tools):
    rounds = [[tool_call("Gmail__search_email")] for _ in range(engine.MAX_TOOL_ROUNDS)]
    events = run(FakeModel(*rounds))
    assert events[-1] == {"type": "error", "message": engine.TOO_MANY_ROUNDS}


def test_model_failure_is_shown(tools):
    events = run(FakeModel([{"type": "text", "text": "Hi"}, ModelError("out of memory")]))
    assert events[-1] == {"type": "error", "message": "out of memory"}


def test_arguments_sent_as_json_text_are_understood(tools):
    run(FakeModel([tool_call("Gmail__search_email", '{"query": "x"}')], []))
    assert tools == [("search", {"query": "x"})]


def test_approval_answers_work_once():
    async def scenario():
        approval_id, decision = approvals.create()
        assert approvals.resolve(approval_id, True) is True
        assert approvals.resolve(approval_id, True) is False
        assert await approvals.wait(approval_id, decision) == approvals.Answer(True)

    asyncio.run(scenario())


async def collect_with_follow_up(events, text):
    collected = []
    async for event in events:
        collected.append(event)
        if event["type"] == "approval":
            assert approvals.send_follow_up(event["id"], text)
    return collected


def test_follow_up_cancels_the_action_and_reaches_the_model(tools):
    """Even a message saying yes must not run anything. Only the Approve button can."""
    model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS)], [{"type": "text", "text": "Changed"}])

    events = asyncio.run(collect_with_follow_up(engine.run_chat(USER_MESSAGE, model, True), "yes, send it"))

    assert tools == []
    assert events[-1] == {"type": "text", "text": "Changed"}
    assert tool_results(model) == [engine.OWNER_SENT_A_MESSAGE]
    assert model.seen_messages[-1][-1] == {"role": "user", "content": "yes, send it"}


def test_follow_up_also_stops_the_rest_of_that_plan(tools):
    second_call = {**tool_call("Gmail__search_email"), "id": "second"}
    model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS), second_call], [])

    asyncio.run(collect_with_follow_up(engine.run_chat(USER_MESSAGE, model, True), "wait"))

    assert tools == []
    assert tool_results(model) == [engine.OWNER_SENT_A_MESSAGE, engine.OWNER_SENT_A_MESSAGE]
    assert model.seen_messages[-1][-1] == {"role": "user", "content": "wait"}


def test_no_model_means_no_integrations_are_loaded(monkeypatch):
    async def fail():
        raise AssertionError("Integrations must not load without a model")

    monkeypatch.setattr(model_slot, "connected_model", None)
    monkeypatch.setattr(service, "load_enabled_integrations", fail)
    response = client.post("/api/chat", json={"messages": USER_MESSAGE})
    assert response.status_code == 503
    assert response.json() == {"error": "No model is connected."}


def test_slot_is_empty_by_default():
    assert model_slot.connected_model is None


def test_chat_route_streams_events_when_a_model_is_plugged_in(tools, monkeypatch):
    model = FakeModel([tool_call("Gmail__search_email")], [{"type": "text", "text": "Done"}])
    monkeypatch.setattr(model_slot, "connected_model", model)

    response = client.post("/api/chat", json={"messages": USER_MESSAGE})

    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert [json.loads(line) for line in response.text.splitlines()] == [
        {"type": "tool", "label": "Gmail → search_email"},
        {"type": "text", "text": "Done"},
    ]


def test_chat_route_only_allows_approval_when_the_client_asks(tools, monkeypatch):
    model = FakeModel([tool_call("Gmail__send_email", SEND_ARGUMENTS)], [])
    monkeypatch.setattr(model_slot, "connected_model", model)

    response = client.post("/api/chat", json={"messages": USER_MESSAGE, "canApprove": "yes"})

    assert response.text == ""
    assert tools == []


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"approved": "yes"},
        {"approved": 1},
        {"followUp": ""},
        {"followUp": "   "},
        {"followUp": 5},
        {"followUp": "go", "approved": True},
    ],
)
def test_invalid_approval_answers_are_rejected(body):
    assert client.post("/api/chat/approvals/x", json=body).status_code == 422


def test_unknown_approval_returns_404():
    assert client.post("/api/chat/approvals/unknown", json={"approved": True}).status_code == 404


def test_approval_route_answers_a_pending_request():
    async def scenario():
        approval_id, decision = approvals.create()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            response = await async_client.post(f"/api/chat/approvals/{approval_id}", json={"approved": True})
        return response.status_code, decision.result()

    assert asyncio.run(scenario()) == (200, approvals.Answer(True))


def test_approval_route_takes_a_follow_up_as_a_no():
    async def scenario():
        approval_id, decision = approvals.create()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
            response = await async_client.post(f"/api/chat/approvals/{approval_id}", json={"followUp": " at 7pm "})
        return response.status_code, decision.result()

    assert asyncio.run(scenario()) == (200, approvals.Answer(False, "at 7pm"))


def test_follow_up_to_an_expired_request_returns_404():
    assert client.post("/api/chat/approvals/unknown", json={"followUp": "x"}).status_code == 404


def test_real_gmail_server_only_lets_reading_skip_approval(monkeypatch):
    """Starts the real Gmail process through the real toolbox; no network is touched."""
    server = {
        "name": "Gmail",
        "transport": "stdio",
        "command": service.sys.executable,
        "args": service.GMAIL_SERVER_ARGS,
        "env": {"GMAIL_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "x", "PYTHONPATH": str(service.config.ROOT_DIR)},
        "headers": {},
        "url": None,
    }

    async def scenario():
        async with toolbox.open_toolbox([server], []) as box:
            return {name: box.needs_approval(name) for name in box.tools}

    assert asyncio.run(scenario()) == {
        "Gmail__search_email": False,
        "Gmail__read_email": False,
        "Gmail__mark_email": True,
        "Gmail__archive_email": True,
        "Gmail__trash_email": True,
        "Gmail__send_email": True,
    }
