import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.backend.notes import store
from src.backend.routes import is_same_origin, read_json

logger = logging.getLogger(__name__)

COLORS = ("yellow", "pink", "blue", "green", "purple")
MAX_TEXT_CHARACTERS = 20000


async def require_same_origin(request: Request):
    """Notes are private, so only the app's own page may read or change them."""
    if not is_same_origin(request):
        logger.warning("Rejected a notes request from another origin")
        raise HTTPException(
            status_code=403, detail="Requests from other websites aren't allowed."
        )


router = APIRouter(prefix="/api", dependencies=[Depends(require_same_origin)])


def validate_note_changes(body):
    if not isinstance(body, dict) or not body or set(body) - {"text", "color"}:
        return None
    text = body.get("text")
    if text is not None and (
        not isinstance(text, str) or len(text) > MAX_TEXT_CHARACTERS
    ):
        return None
    color = body.get("color")
    if color is not None and color not in COLORS:
        return None
    return body


def note_not_found():
    return JSONResponse({"error": "Note not found"}, status_code=404)


@router.get("/notes")
async def list_notes():
    return {"notes": await store.list_notes()}


@router.post("/notes", status_code=201)
async def create_note(request: Request):
    body = await read_json(request) or {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "Invalid note"}, status_code=422)
    color = body.get("color", COLORS[0])
    text = body.get("text", "")
    if (
        color not in COLORS
        or not isinstance(text, str)
        or len(text) > MAX_TEXT_CHARACTERS
    ):
        return JSONResponse({"error": "Invalid note"}, status_code=422)
    return await store.create_note(color, text)


@router.patch("/notes/{note_id}")
async def update_note(note_id: int, request: Request):
    changes = validate_note_changes(await read_json(request))
    if changes is None:
        return JSONResponse({"error": "Invalid changes"}, status_code=422)
    if not await store.update_note(note_id, changes):
        return note_not_found()
    return {"ok": True}


@router.delete("/notes/{note_id}")
async def delete_note(note_id: int):
    if not await store.delete_note(note_id):
        return note_not_found()
    return {"ok": True}
