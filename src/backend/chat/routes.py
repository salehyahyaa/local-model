import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.backend.chat import approvals, engine, model_slot
from src.backend.validation import validate_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat")

NO_MODEL_MESSAGE = "No model is connected."
EXPIRED_MESSAGE = "This request has expired."


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
    conversation_id = body.get("conversationId")
    if not isinstance(conversation_id, int) or isinstance(conversation_id, bool):
        conversation_id = None
    from_telegram = body.get("fromTelegram") is True
    events = engine.run_chat(messages, model, can_approve, conversation_id, from_telegram)
    return StreamingResponse(to_lines(events), media_type="application/x-ndjson")


@router.post("/approvals/{approval_id}")
async def answer_approval(approval_id: str, request: Request):
    body = await read_json(request)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Invalid answer"}, status_code=422)
    if "followUp" in body:
        return answer_with_follow_up(approval_id, body)
    if not isinstance(body.get("approved"), bool):
        return JSONResponse({"error": "Invalid answer"}, status_code=422)
    if not approvals.resolve(approval_id, body["approved"]):
        return JSONResponse({"error": EXPIRED_MESSAGE}, status_code=404)
    logger.info("Tool call %s by the owner", "approved" if body["approved"] else "denied")
    return {"ok": True}


def answer_with_follow_up(approval_id, body):
    """A follow-up can't come with a yes, because a message must never approve anything."""
    follow_up = body["followUp"]
    if "approved" in body or not isinstance(follow_up, str) or not follow_up.strip():
        return JSONResponse({"error": "Invalid answer"}, status_code=422)
    if not approvals.send_follow_up(approval_id, follow_up.strip()):
        return JSONResponse({"error": EXPIRED_MESSAGE}, status_code=404)
    logger.info("Tool call replaced by the owner's follow-up")
    return {"ok": True}
