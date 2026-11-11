"""Checks ElevenLabs for call results.

With the webhook set up, results arrive there first and this is only a backup for calls whose webhook is late.
Without it, this is how results arrive. Active calls are read from the database each time, so checking picks
up again after a restart.
"""

import asyncio
import logging

import httpx

from src.backend import config
from src.backend.health import jobs
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
        await save_result(call, result, "check")


async def save_result(call, result, source):
    """Shared by the webhook and the backup check. Only the first to finish a call texts the owner."""
    finished = await store.finish_call(call["id"], result["status"], result["message"], result["booked_time"])
    if finished:
        logger.info("Appointment call %s finished as %s (from %s)", call["id"], result["status"], source)
        await notify.send_result(result["message"])


async def check_soon(elevenlabs_conversation_id):
    """ElevenLabs sends no webhook when its agent fails to start, so each new call is checked once shortly after."""
    await asyncio.sleep(config.APPOINTMENT_CALL_FIRST_CHECK_SECONDS)
    try:
        call = await store.find_active_call(elevenlabs_conversation_id)
        if call is not None:
            await check_call(call, connection.get_api_key())
    except Exception:
        logger.exception("Could not do the first check of an appointment call")


def webhook_is_set_up():
    return bool(config.ELEVENLABS_WEBHOOK_SECRET)


def is_due(call):
    """With the webhook on, a call is only checked here once its webhook is overdue."""
    return not webhook_is_set_up() or call["age_seconds"] > config.APPOINTMENT_CALL_WEBHOOK_GRACE


async def check_active_calls():
    calls = [call for call in await store.list_active_calls() if is_due(call)]
    if not calls:
        return
    api_key = connection.get_api_key()
    for call in calls:
        await check_call(call, api_key)


def seconds_between_checks():
    return config.APPOINTMENT_CALL_BACKUP_POLL_SECONDS if webhook_is_set_up() else config.APPOINTMENT_CALL_POLL_SECONDS


async def run():
    while True:
        try:
            await check_active_calls()
            jobs.succeeded("call_results")
        except Exception:
            # One bad check must not stop results for every later call.
            logger.exception("Could not check appointment calls")
            jobs.failed("call_results", "The last check hit an error. See logs/app.log.")
        await asyncio.sleep(seconds_between_checks())
