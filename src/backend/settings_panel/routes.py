import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.backend.chat import system_prompt
from src.backend.settings_panel import connections

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


def prompt_response(saved):
    return {
        "systemPrompt": system_prompt.DEFAULT_SYSTEM_PROMPT if saved is None else saved,
        "isDefault": saved is None,
        "defaultPrompt": system_prompt.DEFAULT_SYSTEM_PROMPT,
    }


@router.get("/system-prompt")
async def read_system_prompt():
    return prompt_response(await system_prompt.read_saved())


@router.put("/system-prompt")
async def save_system_prompt(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or "systemPrompt" not in body:
        return JSONResponse({"error": "Invalid system prompt"}, status_code=422)
    text = body["systemPrompt"]
    if text is not None and not isinstance(text, str):
        return JSONResponse({"error": "Invalid system prompt"}, status_code=422)
    if text is not None and len(text) > system_prompt.MAX_LENGTH:
        message = f"The system prompt can be up to {system_prompt.MAX_LENGTH} characters."
        return JSONResponse({"error": message}, status_code=422)
    await system_prompt.save(text)
    logger.info("System prompt %s", "reset to the default" if text is None else "changed")
    return prompt_response(text)


@router.get("/connections")
async def list_connections():
    return {
        "services": await asyncio.to_thread(connections.list_services),
        "integrations": await connections.list_integrations(),
    }
