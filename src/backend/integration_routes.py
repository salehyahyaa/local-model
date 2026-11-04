import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src.backend.integrations import api_store, mcp_store, service
from src.backend.integrations.errors import DuplicateNameError
from src.backend.integrations.validation import (
    validate_api_integration,
    validate_enabled_change,
    validate_mcp_server,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/integrations")

ENABLE_FUNCTIONS = {"mcp": mcp_store.set_enabled, "api": api_store.set_enabled}
REMOVE_FUNCTIONS = {"mcp": service.remove_mcp_server, "api": service.remove_api_integration}


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


@router.post("/mcp", status_code=201)
async def add_mcp_server(request: Request):
    server, error = validate_mcp_server(await read_json(request))
    if error:
        return error_response(error, 422)
    try:
        return await service.add_mcp_server(server)
    except DuplicateNameError:
        return duplicate_name_response(server["name"])


@router.post("/api", status_code=201)
async def add_api_integration(request: Request):
    integration, error = validate_api_integration(await read_json(request))
    if error:
        return error_response(error, 422)
    try:
        return await service.add_api_integration(integration)
    except DuplicateNameError:
        return duplicate_name_response(integration["name"])


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
