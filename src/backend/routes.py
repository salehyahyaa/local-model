import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from src.backend import llm
from src.backend.validation import validate_messages

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

NO_MODEL_MESSAGE = "No model is connected."


@router.get("/health")
async def health():
    return {"status": "ok"}


@router.post("/chat")
async def chat(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None

    messages = validate_messages(body)
    if messages is None:
        logger.warning("Rejected invalid chat request")
        return JSONResponse({"error": "Invalid messages"}, status_code=422)

    # Pull the first chunk before streaming so "no model" can be reported as a proper error response.
    reply = llm.stream_chat(messages)
    try:
        first_chunk = await anext(reply)
    except StopAsyncIteration:
        first_chunk = ""
    except llm.ModelUnavailableError as error:
        logger.warning("No model connected: %s", error)
        return JSONResponse({"error": NO_MODEL_MESSAGE}, status_code=503)
    except httpx.HTTPError:
        logger.exception("Model request failed")
        return JSONResponse({"error": "The model request failed."}, status_code=502)

    return StreamingResponse(stream_reply(first_chunk, reply), media_type="text/plain; charset=utf-8")


async def stream_reply(first_chunk, reply):
    yield first_chunk
    try:
        async for text_chunk in reply:
            yield text_chunk
    except (httpx.HTTPError, llm.ModelUnavailableError) as error:
        logger.exception("Model request failed mid-stream")
        yield f"\n[Error: the model stopped responding ({error.__class__.__name__}).]"
