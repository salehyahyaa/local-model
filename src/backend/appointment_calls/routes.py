import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.backend.appointment_calls import connection, store
from src.backend.appointment_calls.validation import validate_connection
from src.backend.integrations.errors import DuplicateNameError
from src.backend.routes import is_same_origin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

HTTP_UNAUTHORIZED = 401
HTTP_FORBIDDEN = 403
HTTP_NOT_FOUND = 404


def error_response(message, status_code):
    return JSONResponse({"error": message}, status_code=status_code)


@router.get("/calls")
async def list_calls():
    return {"calls": await store.list_recent_calls()}


@router.post("/integrations/phone-calls", status_code=201)
async def connect_phone_calls(request: Request):
    if not is_same_origin(request):
        logger.warning("Rejected a phone call connection from another origin")
        return error_response("Requests from other websites aren't allowed.", 403)
    try:
        body = await request.json()
    except ValueError:
        body = None
    settings, error = validate_connection(body)
    if error:
        return error_response(error, 422)
    try:
        return await connection.connect(settings)
    except (connection.AgentNotAllowed, connection.PhoneNumberNotFound) as problem:
        return error_response(str(problem), 422)
    except DuplicateNameError:
        return error_response("Phone calls are already connected. Remove them first to change the settings.", 409)
    except httpx.HTTPStatusError as problem:
        status = problem.response.status_code
        if status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN):
            return error_response("ElevenLabs rejected that API key.", 422)
        if status == HTTP_NOT_FOUND:
            return error_response("ElevenLabs couldn't find that agent ID.", 422)
        return error_response("ElevenLabs had a problem. Try again.", 502)
    except (httpx.HTTPError, ValueError):
        logger.warning("Could not reach ElevenLabs to check the connection")
        return error_response("Couldn't reach ElevenLabs. Check your internet connection and try again.", 502)
