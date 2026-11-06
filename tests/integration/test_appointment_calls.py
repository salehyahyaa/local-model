"""Appointment calls against a real database, with a fake ElevenLabs."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx

from src.backend import db, store as chat_store
from src.backend.appointment_calls import client, connection, poller, store, tool
from src.backend.integrations.toolbox import Toolbox

FUTURE = datetime(2026, 11, 10, 19, 0, tzinfo=timezone.utc) + timedelta(days=365)
SLOT = {"start": FUTURE.isoformat(), "end": (FUTURE + timedelta(hours=2)).isoformat()}
ARGUMENTS = {
    "kind": "appointment",
    "contact_name": "Dr Lee",
    "phone_number": "+14155550123",
    "reason": "A check-up",
    "timezone": "America/New_York",
    "deadline": (FUTURE + timedelta(days=1)).isoformat(),
    "allowed_slots": [SLOT],
}
CONNECTION = {"owner_name": "Sam", "api_key": "key", "agent_id": "agent1", "phone_number_id": "phone1"}
OWN_MODEL_AGENT = {"conversation_config": {"agent": {"prompt": {"llm": "custom-llm"}}}}


def fake_elevenlabs(monkeypatch, dialed, conversation=None):
    def handler(request):
        if request.url.path.startswith("/v1/convai/agents/"):
            return httpx.Response(200, json=OWN_MODEL_AGENT)
        if request.url.path == "/v1/convai/twilio/outbound-call":
            dialed.append(json.loads(request.read()))
            return httpx.Response(
                200, json={"success": True, "message": "ok", "conversation_id": f"c{len(dialed)}", "callSid": "CA1"}
            )
        return httpx.Response(200, json=conversation)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        client,
        "create_client",
        lambda api_key: real_client(base_url="https://elevenlabs.test", transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(connection, "get_api_key", lambda: "key")


def run_with_database(database_url, monkeypatch, scenario):
    monkeypatch.setattr(db, "DATABASE_URL", database_url)

    async def run():
        await db.connect()
        try:
            return await scenario()
        finally:
            await db.disconnect()

    return asyncio.run(run())


async def connect_and_create_chat():
    await store.create_connection(CONNECTION)
    return (await chat_store.create_conversation())["id"]


async def chat_messages(conversation_id):
    rows = await db.pool.fetch(
        "SELECT role, content FROM messages WHERE conversation_id = $1 ORDER BY id", conversation_id
    )
    return [tuple(row) for row in rows]


def test_a_call_runs_from_tool_to_result_in_the_chat(test_database_url, monkeypatch):
    dialed = []
    conversation = {
        "status": "done",
        "analysis": {
            "transcript_summary": "They agreed.",
            "data_collection_results": {
                "booked": {"value": True},
                "appointment_time": {"value": (FUTURE + timedelta(minutes=30)).isoformat()},
            },
        },
    }
    fake_elevenlabs(monkeypatch, dialed, conversation)

    async def scenario():
        chat_id = await connect_and_create_chat()
        box = Toolbox()
        await tool.register(box, chat_id)
        assert box.needs_approval("Phone_calls__place_appointment_call")

        _, result = await box.call("Phone_calls__place_appointment_call", ARGUMENTS)
        assert result.startswith("Calling Dr Lee"), result
        assert dialed[0]["agent_id"] == "agent1"
        assert dialed[0]["conversation_initiation_client_data"]["dynamic_variables"]["owner_name"] == "Sam"

        recent = await store.list_recent_calls()
        assert recent[0]["status"] == "calling"
        assert "phoneNumber" not in recent[0]

        await poller.check_active_calls()
        recent = await store.list_recent_calls()
        assert recent[0]["status"] == "booked"
        row = await db.pool.fetchrow("SELECT booked_time, twilio_call_sid FROM appointment_calls")
        assert row["booked_time"] == FUTURE + timedelta(minutes=30)
        assert row["twilio_call_sid"] == "CA1"

        messages = await chat_messages(chat_id)
        assert len(messages) == 1
        assert messages[0][0] == "assistant"
        assert messages[0][1].startswith("Booked with Dr Lee")

        # A second check finds nothing to do, so the result isn't posted twice.
        await poller.check_active_calls()
        assert len(await chat_messages(chat_id)) == 1

    run_with_database(test_database_url, monkeypatch, scenario)


def test_only_one_call_runs_at_a_time(test_database_url, monkeypatch):
    dialed = []
    fake_elevenlabs(monkeypatch, dialed, {"status": "in-progress"})

    async def scenario():
        chat_id = await connect_and_create_chat()
        place = tool.make_handler(chat_id)
        first, second = await asyncio.gather(place(ARGUMENTS), place(ARGUMENTS))
        assert len(dialed) == 1
        assert sum(answer.startswith(tool.NOT_PLACED) for answer in (first, second)) == 1

    run_with_database(test_database_url, monkeypatch, scenario)


def test_daily_limit_holds(test_database_url, monkeypatch):
    dialed = []
    fake_elevenlabs(monkeypatch, dialed)
    monkeypatch.setattr(tool, "APPOINTMENT_CALL_DAILY_LIMIT", 2)

    async def scenario():
        chat_id = await connect_and_create_chat()
        place = tool.make_handler(chat_id)
        for _ in range(2):
            assert (await place(ARGUMENTS)).startswith("Calling")
            await db.pool.execute("UPDATE appointment_calls SET status = 'not_booked'")
        answer = await place(ARGUMENTS)
        assert "limit of 2 calls" in answer
        assert len(dialed) == 2

    run_with_database(test_database_url, monkeypatch, scenario)


def test_an_active_call_is_picked_up_after_a_restart(test_database_url, monkeypatch):
    dialed = []
    fake_elevenlabs(monkeypatch, dialed, {"status": "failed"})

    async def before_restart():
        chat_id = await connect_and_create_chat()
        await tool.make_handler(chat_id)(ARGUMENTS)
        return chat_id

    chat_id = run_with_database(test_database_url, monkeypatch, before_restart)

    async def after_restart():
        await poller.check_active_calls()
        assert (await store.list_recent_calls())[0]["status"] == "failed"
        assert len(await chat_messages(chat_id)) == 1

    run_with_database(test_database_url, monkeypatch, after_restart)


def test_a_call_gives_up_after_the_timeout(test_database_url, monkeypatch):
    dialed = []
    fake_elevenlabs(monkeypatch, dialed, {"status": "in-progress"})

    async def scenario():
        chat_id = await connect_and_create_chat()
        await tool.make_handler(chat_id)(ARGUMENTS)
        await poller.check_active_calls()
        assert (await store.list_recent_calls())[0]["status"] == "calling"

        await db.pool.execute("UPDATE appointment_calls SET created_at = now() - interval '2 hours'")
        await poller.check_active_calls()
        assert (await store.list_recent_calls())[0]["status"] == "unknown"

    run_with_database(test_database_url, monkeypatch, scenario)


def test_deleting_the_chat_keeps_the_call_and_posts_nothing(test_database_url, monkeypatch):
    dialed = []
    fake_elevenlabs(monkeypatch, dialed, {"status": "failed"})

    async def scenario():
        chat_id = await connect_and_create_chat()
        await tool.make_handler(chat_id)(ARGUMENTS)
        await chat_store.delete_conversation(chat_id)
        await poller.check_active_calls()
        recent = await store.list_recent_calls()
        assert recent[0]["status"] == "failed"
        assert recent[0]["conversationId"] is None

    run_with_database(test_database_url, monkeypatch, scenario)


def test_connection_can_be_toggled_removed_and_stops_the_tool(test_database_url, monkeypatch):
    async def registered():
        box = Toolbox()
        await tool.register(box, 1)
        return box.has_tools()

    async def scenario():
        assert await registered() is False
        created = await store.create_connection(CONNECTION)
        assert await registered() is True
        assert await store.set_enabled(created["id"], False) is True
        assert await registered() is False
        assert (await connection.list_public())[0]["enabled"] is False
        assert await store.delete_connection(created["id"]) is True
        assert await connection.list_public() == []

    run_with_database(test_database_url, monkeypatch, scenario)
