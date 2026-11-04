import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.backend import store, stt
from src.backend.models.image_generation import store as image_store
from src.backend.validation import (
    is_valid_message,
    validate_conversation_changes,
    validate_messages,
    validate_settings_changes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

NO_MODEL_MESSAGE = "No model is connected."
MAX_AUDIO_BYTES = 10 * 1024 * 1024


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/models")
async def list_models():
    # No model is connected to this app. Add one only with the owner's explicit permission (see CLAUDE.md).
    return {"models": [], "defaultModel": None}


@router.post("/chat")
async def chat(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None

    if validate_messages(body) is None:
        logger.warning("Rejected invalid chat request")
        return JSONResponse({"error": "Invalid messages"}, status_code=422)
    return JSONResponse({"error": NO_MODEL_MESSAGE}, status_code=503)


@router.post("/transcribe")
async def transcribe(request: Request):
    audio = await request.body()
    if not audio or len(audio) > MAX_AUDIO_BYTES:
        logger.warning("Rejected transcribe request (%d bytes)", len(audio))
        return JSONResponse({"error": "Invalid audio"}, status_code=422)

    content_type = request.headers.get("content-type", "audio/wav")
    try:
        text = await stt.transcribe(audio, content_type)
    except stt.TranscriptionUnavailableError as error:
        logger.warning("Speech-to-text unavailable: %s", error)
        return JSONResponse({"error": "Speech-to-text is not configured."}, status_code=503)
    except (httpx.HTTPError, KeyError, ValueError):
        logger.exception("Transcription request failed")
        return JSONResponse({"error": "The transcription request failed."}, status_code=502)

    return {"text": text}


async def read_json(request):
    try:
        return await request.json()
    except ValueError:
        return None


def not_found():
    return JSONResponse({"error": "Conversation not found"}, status_code=404)


@router.get("/state")
async def get_state():
    return await store.get_state()


@router.post("/conversations", status_code=201)
async def create_conversation():
    return await store.create_conversation()


@router.patch("/conversations/{conversation_id}")
async def update_conversation(conversation_id: int, request: Request):
    changes = validate_conversation_changes(await read_json(request))
    if changes is None:
        return JSONResponse({"error": "Invalid changes"}, status_code=422)
    if not await store.update_conversation(conversation_id, changes):
        return not_found()
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int):
    image_files = await image_store.files_in_conversation(conversation_id)
    if not await store.delete_conversation(conversation_id):
        return not_found()
    image_store.delete_files(image_files)
    return {"ok": True}


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def add_message(conversation_id: int, request: Request):
    message = await read_json(request)
    if not is_valid_message(message):
        return JSONResponse({"error": "Invalid message"}, status_code=422)
    message_id = await store.add_message(conversation_id, message["role"], message["content"], message.get("model"))
    if message_id is None:
        return not_found()
    return {"id": message_id}


@router.delete("/conversations/{conversation_id}/messages/last")
async def delete_last_message(conversation_id: int):
    if not await store.delete_last_message(conversation_id):
        return not_found()
    return {"ok": True}


@router.patch("/settings")
async def update_settings(request: Request):
    changes = validate_settings_changes(await read_json(request))
    if changes is None:
        return JSONResponse({"error": "Invalid settings"}, status_code=422)
    if not await store.update_settings(changes):
        return not_found()
    return {"ok": True}
