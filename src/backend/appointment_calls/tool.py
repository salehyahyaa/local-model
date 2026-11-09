"""The tool the chat model uses. It needs the owner's approval every time, because it phones a real person."""

import logging

import asyncpg
import httpx

from src.backend import db
from src.backend.appointment_calls import client, connection, outcome, store
from src.backend.appointment_calls.validation import APPOINTMENT, RESERVATION, validate_call

logger = logging.getLogger(__name__)

ACTION_NAME = "place_appointment_call"
NOT_PLACED = "Error: the call was not placed. "
DO_NOT_RETRY = "Do not try again unless the owner asks."
DESCRIPTION = (
    "Phone someone with an AI voice agent to book a reservation or appointment for the owner. Use only when the "
    "owner asks. If the owner didn't give the phone number, time or, for a reservation, the party size, ask in the "
    "chat before using this. Never guess them. The agent can only accept times inside allowed_slots, so check the "
    "owner's calendar first if a calendar tool is available, and remove any slot that conflicts. The result is "
    "posted in this chat and sent to the owner on Telegram when the call ends."
)
TIME_FORMAT = "ISO 8601 with a UTC offset, like 2026-11-10T14:00:00-05:00"
SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": [RESERVATION, APPOINTMENT], "description": "What is being booked."},
        "contact_name": {"type": "string", "description": "Who is being called."},
        "phone_number": {"type": "string", "description": "International format, like +14155550123."},
        "reason": {"type": "string", "description": "What the booking is for. Shared with the person called."},
        "party_size": {"type": "integer", "description": "How many people. Required for a reservation."},
        "booking_name": {
            "type": "string",
            "description": "The name to book under, if the owner gave one. Otherwise leave this out.",
        },
        "timezone": {
            "type": "string",
            "description": "IANA time zone name of the place being called, like America/New_York.",
        },
        "deadline": {"type": "string", "description": f"The appointment must be before this. {TIME_FORMAT}."},
        "allowed_slots": {
            "type": "array",
            "description": "The time ranges the owner can do.",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string", "description": TIME_FORMAT},
                    "end": {"type": "string", "description": TIME_FORMAT},
                },
                "required": ["start", "end"],
            },
        },
    },
    "required": ["kind", "contact_name", "phone_number", "reason", "timezone", "deadline", "allowed_slots"],
}


def build_variables(call, owner_name):
    """What the agent's prompt in ElevenLabs is filled in with."""
    return {
        "owner_name": owner_name,
        "booking_name": call["booking_name"] or owner_name,
        "contact_name": call["contact_name"],
        "reason": call["reason"],
        "timezone": call["timezone"],
        "deadline": outcome.format_time(call["deadline"], call["timezone"]),
        "allowed_slots": outcome.format_slots(call["allowed_slots"], call["timezone"]),
    }


async def place_call(arguments, conversation_id):
    """Returns text for the model. Expected failures are returned, so the chat reply can explain them."""
    call, error = validate_call(arguments)
    if error:
        return f"{NOT_PLACED}{error}"
    if conversation_id is None or not await store.conversation_exists(conversation_id):
        return f"{NOT_PLACED}This chat has no saved conversation to post the result in."

    settings = await connection.load_connection()
    api_key = connection.get_api_key()
    if settings is None or not settings["enabled"] or not api_key:
        return f"{NOT_PLACED}Phone calls aren't connected."

    # Checked on every call: the agent's settings can change in ElevenLabs after it was connected here.
    try:
        await connection.check_agent(api_key, settings["agent_id"])
    except connection.AgentNotAllowed as problem:
        return f"{NOT_PLACED}{problem}"
    except (httpx.HTTPError, ValueError):
        logger.warning("Could not check the ElevenLabs agent before a call")
        return f"{NOT_PLACED}Couldn't check the agent with ElevenLabs."

    call_id = await store.reserve_call(call, conversation_id)
    return await dial(call_id, call, settings, api_key)


async def dial(call_id, call, settings, api_key):
    """The owner hears about a failure here from the model's reply, so it isn't posted to the chat a second time."""
    name = call["contact_name"]
    try:
        conversation, call_sid = await client.start_call(
            api_key,
            settings["agent_id"],
            settings["phone_number_id"],
            call["phone_number"],
            build_variables(call, settings["owner_name"]),
        )
    except client.CallNotPlaced as problem:
        logger.warning("Appointment call %s was not placed", call_id)
        message = f"The call to {name} wasn't placed: {problem}"
        await save_safely(store.finish_call(call_id, "failed", message, post_to_chat=False))
        return f"{NOT_PLACED}{problem} {DO_NOT_RETRY}"
    except client.CallStateUnknown as problem:
        logger.warning("Appointment call %s may or may not have started", call_id)
        message = f"The call to {name} may or may not have started: {problem}"
        await save_safely(store.finish_call(call_id, "unknown", message, post_to_chat=False))
        return f"Error: {message} {DO_NOT_RETRY}"

    logger.info("Started appointment call %s", call_id)
    if not await save_safely(store.save_call_ids(call_id, conversation, call_sid)):
        return f"Calling {name} now, but the result can't be tracked, so it won't appear in this chat. {DO_NOT_RETRY}"
    return f"Calling {name} now. The result will be posted in this chat when the call ends."


async def save_safely(saving):
    """Once a call may have started, a database problem must never be reported as "the call was not placed"."""
    try:
        await saving
    except (db.DatabaseUnavailableError, asyncpg.PostgresError):
        logger.exception("Could not save an appointment call's details")
        return False
    return True


def make_handler(conversation_id):
    async def handler(arguments):
        try:
            return await place_call(arguments, conversation_id)
        except (db.DatabaseUnavailableError, asyncpg.PostgresError):
            logger.exception("The database failed before an appointment call was placed")
            return f"{NOT_PLACED}The database isn't available."

    return handler


async def register(toolbox, conversation_id):
    """Adds the tool when phone calls are connected and turned on in the + menu."""
    settings = await connection.load_connection()
    if settings is None or not settings["enabled"]:
        return
    toolbox.add_tool(connection.NAME, ACTION_NAME, DESCRIPTION, SCHEMA, make_handler(conversation_id))
