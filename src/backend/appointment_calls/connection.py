"""Phone call settings. They come from the config, so the owner only has to ask the model to make a call."""

import asyncio
import logging

import httpx

from src.backend import config
from src.backend.appointment_calls import client
from src.backend.integrations import service

logger = logging.getLogger(__name__)

NAME = "Phone calls"
SETTINGS_ID = 1
WRONG_MODEL_MESSAGE = (
    "This agent can't be used: in ElevenLabs, set its LLM to DeepSeek Flash 4.1 with Backup LLM disabled, "
    "or to Custom LLM without a custom backup list."
)
HTTP_NOT_FOUND = 404
PHONE_NUMBER_NOT_FOUND_MESSAGE = "ElevenLabs couldn't find that phone number ID."


class AgentNotAllowed(Exception):
    """The agent could use a model other than the approved ones."""


class PhoneNumberNotFound(Exception):
    """ElevenLabs doesn't have that phone number ID."""


def get_api_key():
    return config.ELEVENLABS_API_KEY


async def load_connection():
    """None until the agent, phone number, owner name and API key are all set in the config."""
    settings = {
        "id": SETTINGS_ID,
        "owner_name": config.CALL_OWNER_NAME,
        "agent_id": config.ELEVENLABS_AGENT_ID,
        "phone_number_id": config.ELEVENLABS_PHONE_NUMBER_ID,
        "enabled": True,
    }
    if not all(settings.values()) or not get_api_key():
        return None
    return settings


async def check_agent(api_key, agent_id):
    agent = await client.get_agent(api_key, agent_id)
    if not client.uses_only_owner_model(agent):
        raise AgentNotAllowed(WRONG_MODEL_MESSAGE)


async def check_phone_number(api_key, phone_number_id):
    try:
        await client.get_phone_number(api_key, phone_number_id)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == HTTP_NOT_FOUND:
            raise PhoneNumberNotFound(PHONE_NUMBER_NOT_FOUND_MESSAGE) from error
        raise


async def check_saved_connection(settings):
    try:
        await check_agent(get_api_key(), settings["agent_id"])
        await check_phone_number(get_api_key(), settings["phone_number_id"])
    except httpx.HTTPStatusError as error:
        status = error.response.status_code
        if status in (401, 403):
            raise AgentNotAllowed("ElevenLabs rejected the API key.") from error
        if status == HTTP_NOT_FOUND:
            raise AgentNotAllowed("ElevenLabs couldn't find the agent ID.") from error
        raise


async def check_health():
    settings = await load_connection()
    if settings is None:
        return []
    try:
        await asyncio.wait_for(check_saved_connection(settings), service.HEALTH_CHECK_TIMEOUT)
    except (AgentNotAllowed, PhoneNumberNotFound) as problem:
        return [{"kind": "phone", "id": settings["id"], "problem": str(problem)}]
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
        return [{"kind": "phone", "id": settings["id"], "problem": "Couldn't reach ElevenLabs."}]
    return [{"kind": "phone", "id": settings["id"], "problem": None}]
