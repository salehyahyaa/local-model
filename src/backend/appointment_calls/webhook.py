"""Receives call results from ElevenLabs' post-call webhook, the main way results arrive.

Every request is checked against the shared secret first, because the tunnel makes this address public.
"""

import hashlib
import hmac
import json
import logging
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.backend import config
from src.backend.appointment_calls import outcome, poller, store

logger = logging.getLogger(__name__)

router = APIRouter()

SIGNATURE_HEADER = "elevenlabs-signature"
# ElevenLabs' own SDK accepts signatures up to 30 minutes old; older ones could be replays.
MAX_SIGNATURE_AGE_SECONDS = 30 * 60
TRANSCRIPT_EVENT = "post_call_transcription"
FAILED_TO_CONNECT_EVENT = "call_initiation_failure"


def is_signed(raw_body, header, secret, now=None):
    """The header looks like "t=<unix seconds>,v0=<hex HMAC-SHA256 of '<t>.<body>'>"."""
    if not header or not secret:
        return False
    parts = dict(part.split("=", 1) for part in header.split(",") if "=" in part)
    timestamp, signature = parts.get("t", ""), parts.get("v0", "")
    if not timestamp.isdigit() or not signature:
        return False
    now = time.time() if now is None else now
    if now - int(timestamp) > MAX_SIGNATURE_AGE_SECONDS:
        return False
    message = f"{timestamp}.".encode() + raw_body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def read_result(event, call):
    """The result for this event, or None for events that don't finish a call."""
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if event.get("type") == FAILED_TO_CONNECT_EVENT:
        return outcome.did_not_connect(call, data.get("failure_reason"))
    if event.get("type") == TRANSCRIPT_EVENT:
        # The payload has the same shape as a conversation read from the API.
        return outcome.read_outcome({**data, "status": data.get("status") or "done"}, call)
    return None


async def handle_event(event):
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    conversation_id = data.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id:
        return
    call = await store.find_active_call(conversation_id)
    if call is None:
        # Not one of ours, already finished, or its ids aren't saved yet; the backup check covers the last case.
        logger.info("Webhook %s for a call with no pending result", event.get("type"))
        return
    result = read_result(event, call)
    if result is not None:
        await poller.save_result(call, result, "webhook")


@router.post("/api/calls/webhook")
async def receive(request: Request):
    raw_body = await request.body()
    if not is_signed(raw_body, request.headers.get(SIGNATURE_HEADER), config.ELEVENLABS_WEBHOOK_SECRET):
        logger.warning("Rejected a call webhook with a missing or wrong signature")
        return JSONResponse({"error": "Invalid signature."}, status_code=401)
    try:
        event = json.loads(raw_body)
    except ValueError:
        return JSONResponse({"error": "Invalid JSON."}, status_code=400)
    if isinstance(event, dict):
        await handle_event(event)
    # ElevenLabs turns the webhook off after repeated failures, so anything signed is acknowledged.
    return {"ok": True}
