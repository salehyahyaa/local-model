import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.backend.chat import approvals, engine, model_slot
from src.backend.validation import validate_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat")

NO_MODEL_MESSAGE = "No model is connected."


async def read_json(request):
    try:
        return await request.json()
    except ValueError:
        return None


async def to_lines(events):
    async for event in events:
        yield json.dumps(event) + "\n"


@router.post("")
async def chat(request: Request):
    body = await read_json(request)
    messages = validate_messages(body)
    if messages is None:
        logger.warning("Rejected invalid chat request")
        return JSONResponse({"error": "Invalid messages"}, status_code=422)

    model = model_slot.connected_model
    if model is None:
        return JSONResponse({"error": NO_MODEL_MESSAGE}, status_code=503)

    can_approve = body.get("canApprove") is True
    events = engine.run_chat(messages, model, can_approve)
    return StreamingResponse(to_lines(events), media_type="application/x-ndjson")


@router.post("/approvals/{approval_id}")
async def answer_approval(approval_id: str, request: Request):
    body = await read_json(request)
    if not isinstance(body, dict) or not isinstance(body.get("approved"), bool):
        return JSONResponse({"error": "Invalid answer"}, status_code=422)
    if not approvals.resolve(approval_id, body["approved"]):
        return JSONResponse({"error": "This request has expired."}, status_code=404)
    logger.info("Tool call %s by the owner", "approved" if body["approved"] else "denied")
    return {"ok": True}
