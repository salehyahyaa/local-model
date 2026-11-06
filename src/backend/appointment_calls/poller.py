"""Checks ElevenLabs for call results, so the app never needs a public address.

Active calls are read from the database each time, so checking picks up again after a restart.
"""

import asyncio
import logging

import httpx

from src.backend import config
from src.backend.appointment_calls import client, connection, notify, outcome, store

logger = logging.getLogger(__name__)


async def check_call(call, api_key):
    result = None
    if call["elevenlabs_conversation_id"] and api_key:
        try:
            conversation = await client.get_conversation(api_key, call["elevenlabs_conversation_id"])
            result = outcome.read_outcome(conversation, call)
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("Could not check appointment call %s: %s", call["id"], type(error).__name__)

    if result is None and call["age_seconds"] > config.APPOINTMENT_CALL_RESULT_TIMEOUT:
        result = outcome.timed_out(call, config.APPOINTMENT_CALL_RESULT_TIMEOUT)
    if result is not None:
        finished = await store.finish_call(call["id"], result["status"], result["message"], result["booked_time"])
        logger.info("Appointment call %s finished as %s", call["id"], result["status"])
        if finished:
            await notify.send_result(result["message"])


async def check_active_calls():
    calls = await store.list_active_calls()
    if not calls:
        return
    api_key = connection.get_api_key()
    for call in calls:
        await check_call(call, api_key)


async def run():
    while True:
        try:
            await check_active_calls()
        except Exception:
            # One bad check must not stop results for every later call.
            logger.exception("Could not check appointment calls")
        await asyncio.sleep(config.APPOINTMENT_CALL_POLL_SECONDS)
