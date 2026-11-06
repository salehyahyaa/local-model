"""Talks to ElevenLabs. Twilio needs no code here: its number is imported into ElevenLabs, which places the call."""

import httpx

from src.backend import config

CUSTOM_LLM = "custom-llm"
FALLS_BACK_TO_HOSTED_MODELS = "override"
MAX_ERROR_CHARACTERS = 300


class CallNotPlaced(Exception):
    """The call definitely didn't start. Its text is safe to show."""


class CallStateUnknown(Exception):
    """The request may have reached ElevenLabs, so a phone may be ringing. Never retry this automatically."""


def create_client(api_key):
    return httpx.AsyncClient(
        base_url=config.ELEVENLABS_API_URL,
        headers={"xi-api-key": api_key},
        timeout=config.ELEVENLABS_TIMEOUT,
    )


async def get_agent(api_key, agent_id):
    async with create_client(api_key) as client:
        response = await client.get(f"/v1/convai/agents/{agent_id}")
    response.raise_for_status()
    return response.json()


def uses_only_owner_model(agent):
    """New agents default to a hosted model, and a backup list can hand a call to one. Neither is allowed here."""
    try:
        prompt = agent["conversation_config"]["agent"]["prompt"]
    except (KeyError, TypeError):
        return False
    backup = prompt.get("backup_llm_config") or {}
    return prompt.get("llm") == CUSTOM_LLM and backup.get("preference") != FALLS_BACK_TO_HOSTED_MODELS


async def start_call(api_key, agent_id, phone_number_id, to_number, variables):
    """Returns (ElevenLabs conversation id, Twilio call SID)."""
    body = {
        "agent_id": agent_id,
        "agent_phone_number_id": phone_number_id,
        "to_number": to_number,
        "call_recording_enabled": False,
        "conversation_initiation_client_data": {"dynamic_variables": variables},
    }
    try:
        async with create_client(api_key) as client:
            response = await client.post("/v1/convai/twilio/outbound-call", json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout) as error:
        raise CallNotPlaced("Couldn't reach ElevenLabs.") from error
    except httpx.HTTPError as error:
        raise CallStateUnknown("ElevenLabs didn't answer in time.") from error

    if response.is_client_error:
        raise CallNotPlaced(f"ElevenLabs refused the call (HTTP {response.status_code}): {error_text(response)}")
    if response.is_error:
        raise CallStateUnknown(f"ElevenLabs had an error (HTTP {response.status_code}).")

    try:
        result = response.json()
    except ValueError as error:
        raise CallStateUnknown("ElevenLabs sent an answer that couldn't be read.") from error
    if not isinstance(result, dict):
        raise CallStateUnknown("ElevenLabs sent an answer that couldn't be read.")
    if result.get("success") is False:
        raise CallNotPlaced(f"ElevenLabs didn't place the call: {str(result.get('message'))[:MAX_ERROR_CHARACTERS]}")
    if not result.get("conversation_id"):
        raise CallStateUnknown("ElevenLabs didn't say which call it started.")
    return result["conversation_id"], result.get("callSid")


async def get_conversation(api_key, conversation_id):
    async with create_client(api_key) as client:
        response = await client.get(f"/v1/convai/conversations/{conversation_id}")
    response.raise_for_status()
    return response.json()


def error_text(response):
    return response.text[:MAX_ERROR_CHARACTERS]
