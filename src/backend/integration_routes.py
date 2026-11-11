import asyncio
import html
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from src.backend.integrations import api_store, mcp_store, service
from src.backend.integrations.errors import DuplicateNameError, LoginNotConfirmed, McpError
from src.backend.integrations.gmail.mailbox import GmailLoginError
from src.backend.integrations.oauth import OAuthError
from src.backend.integrations.validation import (
    validate_api_integration,
    validate_enabled_change,
    validate_gmail_connection,
    validate_google_calendar_connection,
    validate_mcp_server,
)
from src.backend.routes import is_same_origin

logger = logging.getLogger(__name__)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
SIGN_IN_FINISHED_SCRIPT = '<script>new BroadcastChannel("mcp-sign-in").postMessage("finished");window.close();</script>'


async def require_same_origin(request: Request):
    """Adding an integration can run a command, so other websites must not be able to send these requests."""
    if not is_same_origin(request):
        logger.warning("Rejected an integration request from another origin")
        raise HTTPException(status_code=403, detail="Requests from other websites aren't allowed.")


router = APIRouter(prefix="/api/integrations", dependencies=[Depends(require_same_origin)])

ENABLE_FUNCTIONS = {"mcp": mcp_store.set_enabled, "api": api_store.set_enabled}
REMOVE_FUNCTIONS = {
    "mcp": service.remove_mcp_server,
    "api": service.remove_api_integration,
}


def is_local_request(request):
    return request.url.hostname in LOCAL_HOSTS and request.client is not None and request.client.host in LOCAL_HOSTS


def sign_in_page(message, finished):
    script = SIGN_IN_FINISHED_SCRIPT if finished else ""
    return HTMLResponse(f"<!doctype html><title>Sign-in</title><p>{html.escape(message)}</p>{script}")


async def read_json(request):
    try:
        return await request.json()
    except ValueError:
        return None


def error_response(message, status_code):
    return JSONResponse({"error": message}, status_code=status_code)


def duplicate_name_response(name):
    return error_response(f"An integration called '{name}' already exists.", 409)


@router.get("")
async def list_integrations():
    return await service.list_integrations()


@router.get("/health")
async def integration_health():
    return {"integrations": await service.check_health()}


@router.post("/mcp", status_code=201)
async def add_mcp_server(request: Request):
    server, error = validate_mcp_server(await read_json(request))
    if error:
        return error_response(error, 422)
    if server["transport"] == "stdio" and not is_local_request(request):
        logger.warning("Rejected a local command integration from outside this computer")
        return error_response("Local commands can only be added from this computer.", 403)
    try:
        if server.get("authType") == "oauth":
            redirect_uri = str(request.url_for("finish_mcp_sign_in"))
            return {"authorizationUrl": await service.begin_mcp_sign_in(server, redirect_uri)}
        return await service.add_mcp_server(server)
    except DuplicateNameError:
        return duplicate_name_response(server["name"])
    except OAuthError as sign_in_error:
        return error_response(str(sign_in_error), 422)
    except McpError as connection_error:
        return error_response(f"Couldn't connect to that server: {connection_error}", 422)


@router.get("/mcp/oauth/callback")
async def finish_mcp_sign_in(state: str = "", code: str = "", error: str = ""):
    """The service sends the browser back here after sign-in, so the answer is a page and not JSON."""
    if error or not code:
        return sign_in_page("Sign-in was cancelled. You can close this tab.", finished=False)
    try:
        await service.finish_mcp_sign_in(state, code)
    except DuplicateNameError:
        return sign_in_page("An integration with this name already exists. You can close this tab.", finished=False)
    except OAuthError as sign_in_error:
        return sign_in_page(f"{sign_in_error} You can close this tab.", finished=False)
    except McpError as connection_error:
        return sign_in_page(f"Signed in, but couldn't connect: {connection_error}", finished=False)
    return sign_in_page("Signed in. You can close this tab.", finished=True)


@router.post("/api", status_code=201)
async def add_api_integration(request: Request):
    integration, error = validate_api_integration(await read_json(request))
    if error:
        return error_response(error, 422)
    try:
        return await service.add_api_integration(integration)
    except DuplicateNameError:
        return duplicate_name_response(integration["name"])
    except LoginNotConfirmed as problem:
        return error_response(str(problem), 422)


@router.post("/gmail", status_code=201)
async def connect_gmail(request: Request):
    connection, error = validate_gmail_connection(await read_json(request))
    if error:
        return error_response(error, 422)
    try:
        return await service.connect_gmail(connection)
    except DuplicateNameError:
        return error_response("Gmail is already connected. Remove it first to use a different account.", 409)
    except GmailLoginError:
        return error_response(
            "Gmail rejected that. Check the address, and use an app password, not your regular password.", 422
        )
    except (OSError, asyncio.TimeoutError):
        logger.warning("Could not reach Gmail to check the login")
        return error_response("Couldn't reach Gmail. Check your internet connection and try again.", 502)


@router.post("/google-calendar", status_code=201)
async def connect_google_calendar(request: Request):
    connection, error = validate_google_calendar_connection(await read_json(request))
    if error:
        return error_response(error, 422)
    redirect_uri = str(request.url_for("finish_google_calendar_sign_in"))
    try:
        return {"authorizationUrl": await service.begin_google_calendar_sign_in(connection, redirect_uri)}
    except DuplicateNameError:
        return error_response("Google Calendar is already connected.", 409)


@router.get("/google-calendar/callback")
async def finish_google_calendar_sign_in(state: str = "", code: str = "", error: str = ""):
    """Google sends the browser back here after sign-in, so the answer is a page and not JSON."""
    if error or not code:
        return sign_in_page("Sign-in was cancelled. You can close this tab.", finished=False)
    try:
        await service.finish_google_calendar_sign_in(state, code)
    except DuplicateNameError:
        return sign_in_page("Google Calendar is already connected. You can close this tab.", finished=False)
    except OAuthError as sign_in_error:
        return sign_in_page(f"{sign_in_error} You can close this tab.", finished=False)
    return sign_in_page("Signed in. You can close this tab.", finished=True)


@router.patch("/{kind}/{integration_id}")
async def set_enabled(kind: str, integration_id: int, request: Request):
    enabled = validate_enabled_change(await read_json(request))
    if kind not in ENABLE_FUNCTIONS or enabled is None:
        return error_response("Invalid change", 422)
    if not await ENABLE_FUNCTIONS[kind](integration_id, enabled):
        return error_response("Integration not found", 404)
    return {"ok": True}


@router.delete("/{kind}/{integration_id}")
async def remove_integration(kind: str, integration_id: int):
    if kind not in REMOVE_FUNCTIONS:
        return error_response("Integration not found", 404)
    if not await REMOVE_FUNCTIONS[kind](integration_id):
        return error_response("Integration not found", 404)
    return {"ok": True}
