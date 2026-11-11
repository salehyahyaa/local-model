import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse

from src.backend import store, stt
from src.backend.attachments import documents
from src.backend.chat import model_slot
from src.backend.models.image_generation import store as image_store
from src.backend.validation import (
    is_valid_message,
    validate_conversation_changes,
    validate_settings_changes,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

WEBSOCKET_POLICY_VIOLATION = 1008
MAX_CLIENT_ERROR_CHARACTERS = 4000


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.get("/models")
async def list_models():
    # Models are connected only with the owner's explicit permission (see CLAUDE.md).
    name = getattr(model_slot.connected_model, "name", None)
    return {"models": [name] if name else [], "defaultModel": name}


@router.post("/client-errors", status_code=204)
async def log_client_error(request: Request):
    body = await read_json(request)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Invalid error report"}, status_code=422)
    # %r keeps the browser's text on one line, so it can't fake extra entries in the log.
    logger.error(
        "Browser error: %r %r",
        str(body.get("message"))[:MAX_CLIENT_ERROR_CHARACTERS],
        str(body.get("stack"))[:MAX_CLIENT_ERROR_CHARACTERS],
    )


def is_same_origin(websocket: WebSocket):
    """WebSockets skip the browser's cross-site protection, so other websites must be turned away here."""
    origin = websocket.headers.get("origin")
    return origin is None or urlparse(origin).netloc == websocket.headers.get("host")


@router.websocket("/transcribe/stream")
async def transcribe_stream(websocket: WebSocket):
    if not is_same_origin(websocket):
        logger.warning("Rejected transcription stream from another origin")
        await websocket.close(code=WEBSOCKET_POLICY_VIOLATION)
        return

    await websocket.accept()
    await stt.stream_transcription(websocket)
    try:
        await websocket.close()
    except RuntimeError:
        logger.debug("Browser had already closed the transcription stream")


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
    document_keys = await documents.storage_keys_in_conversation(conversation_id)
    if not await store.delete_conversation(conversation_id):
        return not_found()
    image_store.delete_files(image_files)
    documents.delete_files(document_keys)
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


@router.delete("/conversations/{conversation_id}/messages")
async def clear_conversation(conversation_id: int):
    image_files = await image_store.files_in_conversation(conversation_id)
    document_keys = await documents.storage_keys_in_conversation(conversation_id)
    if not await store.clear_conversation(conversation_id):
        return not_found()
    image_store.delete_files(image_files)
    documents.delete_files(document_keys)
    return {"ok": True}


@router.delete("/conversations/{conversation_id}/messages/last")
async def delete_last_message(conversation_id: int):
    image_files = await store.image_files_of_last_message(conversation_id)
    document_keys = await documents.storage_keys_of_last_message(conversation_id)
    if not await store.delete_last_message(conversation_id):
        return not_found()
    image_store.delete_files(image_files)
    documents.delete_files(document_keys)
    return {"ok": True}


@router.patch("/settings")
async def update_settings(request: Request):
    changes = validate_settings_changes(await read_json(request))
    if changes is None:
        return JSONResponse({"error": "Invalid settings"}, status_code=422)
    if not await store.update_settings(changes):
        return not_found()
    return {"ok": True}
