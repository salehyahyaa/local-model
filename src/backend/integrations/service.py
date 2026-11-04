import base64
import logging

import asyncpg

from src.backend import db
from src.backend.integrations import api_store, env_secrets, mcp_store
from src.backend.integrations.errors import DuplicateNameError

logger = logging.getLogger(__name__)


def build_auth_headers(integration_name, auth, secrets_to_save):
    """Returns headers holding only ${SECRET} references; the real values go to the keychain."""
    auth_type = auth.get("authType") or ("apiKey" if auth.get("apiKey") else "none")
    if auth_type == "basic":
        name = env_secrets.secret_name(integration_name, "BASIC_AUTH")
        credentials = f"{auth['username']}:{auth['password']}".encode()
        secrets_to_save[name] = base64.b64encode(credentials).decode()
        return {"Authorization": "Basic " + env_secrets.reference(name)}
    if auth_type == "apiKey":
        name = env_secrets.secret_name(integration_name, "API_KEY")
        secrets_to_save[name] = auth["apiKey"]
        return {auth["authHeader"]: auth["authPrefix"] + env_secrets.reference(name)}
    return {}


def build_environment(integration_name, entries, secrets_to_save):
    environment = {}
    for entry in entries:
        name = env_secrets.secret_name(integration_name, entry["name"])
        secrets_to_save[name] = entry["value"]
        environment[entry["name"]] = env_secrets.reference(name)
    return environment


async def save_with_secrets(integration_name, secrets_to_save, create_record):
    for name in secrets_to_save:
        if env_secrets.secret_exists(name):
            raise DuplicateNameError(integration_name)
    for name, value in secrets_to_save.items():
        env_secrets.save_secret(name, value)
    try:
        return await create_record()
    except Exception:
        for name in secrets_to_save:
            env_secrets.remove_secret(name)
        raise


async def add_mcp_server(server):
    secrets_to_save = {}
    record = {"name": server["name"], "transport": server["transport"]}
    if server["transport"] == "http":
        record["url"] = server["url"]
        record["headers"] = build_auth_headers(server["name"], server, secrets_to_save)
    else:
        record["command"] = server["command"]
        record["args"] = server["args"]
        record["env"] = build_environment(server["name"], server["env"], secrets_to_save)

    created = await save_with_secrets(server["name"], secrets_to_save, lambda: mcp_store.create_server(record))
    logger.info("Added MCP server %r", created["name"])
    return public_mcp_server(created)


async def add_api_integration(integration):
    secrets_to_save = {}
    record = {
        "name": integration["name"],
        "description": integration["description"],
        "method": integration["method"],
        "url": integration["url"],
        "parameters": integration["parameters"],
        "headers": build_auth_headers(integration["name"], integration, secrets_to_save),
    }
    created = await save_with_secrets(
        integration["name"], secrets_to_save, lambda: api_store.create_integration(record)
    )
    logger.info("Added API integration %r", created["name"])
    return public_api_integration(created)


def remove_secrets(*mappings):
    for mapping in mappings:
        for name in env_secrets.find_references(mapping):
            env_secrets.remove_secret(name)


async def remove_mcp_server(server_id):
    deleted = await mcp_store.delete_server(server_id)
    if deleted is None:
        return False
    remove_secrets(deleted["headers"], deleted["env"])
    logger.info("Removed MCP server %r", deleted["name"])
    return True


async def remove_api_integration(integration_id):
    deleted = await api_store.delete_integration(integration_id)
    if deleted is None:
        return False
    remove_secrets(deleted["headers"])
    logger.info("Removed API integration %r", deleted["name"])
    return True


def public_mcp_server(server):
    if server["transport"] == "http":
        target = server["url"]
    else:
        target = " ".join([server["command"], *server["args"]])
    return {
        "id": server["id"],
        "kind": "mcp",
        "name": server["name"],
        "transport": server["transport"],
        "target": target,
        "enabled": server["enabled"],
    }


def public_api_integration(integration):
    return {
        "id": integration["id"],
        "kind": "api",
        "name": integration["name"],
        "method": integration["method"],
        "target": integration["url"],
        "description": integration["description"],
        "enabled": integration["enabled"],
    }


async def list_integrations():
    servers = await mcp_store.list_servers()
    integrations = await api_store.list_integrations()
    return {
        "mcpServers": [public_mcp_server(server) for server in servers],
        "apiIntegrations": [public_api_integration(integration) for integration in integrations],
    }


async def load_enabled(list_function, label):
    try:
        return await list_function()
    except db.DatabaseUnavailableError:
        return []
    except asyncpg.UndefinedTableError:
        logger.warning("The %s table is missing; run the database migrations", label)
        return []


async def load_enabled_integrations():
    mcp_servers = await load_enabled(mcp_store.list_enabled_servers, "mcp_servers")
    api_integrations = await load_enabled(api_store.list_enabled_integrations, "api_integrations")
    return mcp_servers, api_integrations
