"""The phone-call integration the owner adds from the + menu."""

import logging

import asyncpg

from src.backend.appointment_calls import client, store
from src.backend.integrations import env_secrets, service
from src.backend.integrations.errors import DuplicateNameError

logger = logging.getLogger(__name__)

NAME = "Phone calls"
API_KEY_SECRET = env_secrets.secret_name(NAME, "API_KEY")
WRONG_MODEL_MESSAGE = (
    "This agent can't be used: it must run on your own model. In ElevenLabs, set its LLM to Custom LLM, "
    "and don't set a custom backup LLM list."
)


class AgentNotAllowed(Exception):
    """The agent could use a model other than the owner's."""


def get_api_key():
    return env_secrets.get_secret(API_KEY_SECRET)


async def check_agent(api_key, agent_id):
    agent = await client.get_agent(api_key, agent_id)
    if not client.uses_only_owner_model(agent):
        raise AgentNotAllowed(WRONG_MODEL_MESSAGE)


async def connect(connection):
    """Checks the key and the agent first, so a mistake shows up here and not later in a chat."""
    await check_agent(connection["api_key"], connection["agent_id"])

    async def create_record():
        try:
            return await store.create_connection(connection)
        except asyncpg.UniqueViolationError as error:
            raise DuplicateNameError(NAME) from error

    created = await service.save_with_secrets(NAME, {API_KEY_SECRET: connection["api_key"]}, create_record)
    logger.info("Connected phone calls")
    return to_public(created)


async def remove(connection_id):
    if not await store.delete_connection(connection_id):
        return False
    env_secrets.remove_secret(API_KEY_SECRET)
    logger.info("Removed phone calls")
    return True


def to_public(connection):
    return {
        "id": connection["id"],
        "kind": "phone",
        "provider": "phone-calls",
        "name": NAME,
        "target": connection["owner_name"],
        "enabled": connection["enabled"],
    }


async def read_connections():
    connection = await store.get_connection()
    return [connection] if connection else []


async def load_connection():
    """None when not connected, or when the database or its table isn't available."""
    connections = await service.load_enabled(read_connections, "phone_call_connections")
    return connections[0] if connections else None


async def list_public():
    connection = await load_connection()
    return [to_public(connection)] if connection else []
