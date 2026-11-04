import logging
from urllib.parse import unquote

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from src.backend import documents, store, stt
from src.backend.config import MAX_DOCUMENT_BYTES
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
MAX_AUDIO_BYTES = 40 * 1024 * 1024  # Fits the 20-minute voice limit in speechDetector.js (16 kHz, 16-bit mono).
MAX_CLIENT_ERROR_CHARACTERS = 4000


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


@router.delete("/conversations/{conversation_id}/messages/last")
async def delete_last_message(conversation_id: int):
    image_files = await store.image_files_of_last_message(conversation_id)
    document_keys = await documents.storage_keys_of_last_message(conversation_id)
    if not await store.delete_last_message(conversation_id):
        return not_found()
    image_store.delete_files(image_files)
    documents.delete_files(document_keys)
    return {"ok": True}


@router.post("/messages/{message_id}/documents", status_code=201)
async def add_document(message_id: int, request: Request):
    """Body is the raw PDF; the file name comes URL-encoded in the X-File-Name header."""
    if request.headers.get("content-type", "").split(";")[0].strip() != documents.PDF_CONTENT_TYPE:
        return JSONResponse({"error": "Only PDF documents can be uploaded."}, status_code=415)
    declared_size = request.headers.get("content-length", "")
    if declared_size.isdigit() and int(declared_size) > MAX_DOCUMENT_BYTES:
        return JSONResponse({"error": f"PDFs can be up to {MAX_DOCUMENT_BYTES // (1024 * 1024)} MB."}, status_code=413)

    file_name = unquote(request.headers.get("x-file-name", ""))
    try:
        document = await documents.add_document(message_id, file_name, await request.body())
    except documents.InvalidDocumentError as error:
        return JSONResponse({"error": str(error)}, status_code=422)
    if document is None:
        return JSONResponse({"error": "Message not found"}, status_code=404)
    return document


@router.get("/documents/{document_id}")
async def get_document(document_id: int):
    found = await documents.find_document(document_id)
    if found is None or not found[0].exists():
        return JSONResponse({"error": "Document not found"}, status_code=404)
    path, file_name = found
    return FileResponse(
        path,
        media_type=documents.PDF_CONTENT_TYPE,
        filename=file_name,
        content_disposition_type="inline",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
    )


@router.patch("/settings")
async def update_settings(request: Request):
    changes = validate_settings_changes(await read_json(request))
    if changes is None:
        return JSONResponse({"error": "Invalid settings"}, status_code=422)
    if not await store.update_settings(changes):
        return not_found()
    return {"ok": True}
