import asyncio
import base64
import logging
import sys

import asyncpg
import httpx

from src.backend import config, db
from src.backend.config import TOOL_TIMEOUT
from src.backend.integrations import api_client, api_store, env_secrets, mcp_store, oauth, toolbox
from src.backend.integrations.errors import DuplicateNameError, LoginNotConfirmed, McpError
from src.backend.integrations.gmail import mailbox
from src.backend.integrations.google_calendar import api as calendar_api
from src.backend.integrations.google_calendar import sign_in as calendar_sign_in

logger = logging.getLogger(__name__)

HEALTH_CHECK_TIMEOUT = 30
GMAIL_NAME = "Gmail"
GMAIL_SERVER_ARGS = ["-m", "src.backend.integrations.gmail.server"]
GOOGLE_CALENDAR_NAME = "Google Calendar"
GOOGLE_CALENDAR_SERVER_ARGS = ["-m", "src.backend.integrations.google_calendar.server"]
GOOGLE_ACCOUNT_KEY = "GOOGLE_ACCOUNT"


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

    created = await save_with_secrets(server["name"], secrets_to_save, lambda: check_and_create_server(record))
    logger.info("Added MCP server %r", created["name"])
    return public_mcp_server(created)


async def check_and_create_server(record):
    await toolbox.check_connection(record)
    return await mcp_store.create_server(record)


async def begin_mcp_sign_in(server, redirect_uri):
    """Returns the address to sign in at; the server is saved once sign-in finishes."""
    if any(existing["name"] == server["name"] for existing in await mcp_store.list_servers()):
        raise DuplicateNameError(server["name"])
    return await oauth.begin_sign_in(
        server["name"], server["url"], server["clientId"], server["clientSecret"], redirect_uri
    )


async def finish_mcp_sign_in(state, code):
    name, url, access_token, saved_state = await oauth.finish_sign_in(state, code)
    access_secret, state_secret, headers, environment = oauth.build_secret_references(name)
    record = {"name": name, "transport": "http", "url": url, "headers": headers, "env": environment}
    created = await save_with_secrets(
        name,
        {access_secret: access_token, state_secret: saved_state},
        lambda: check_and_create_server(record),
    )
    logger.info("Added MCP server %r with sign-in", created["name"])
    return public_mcp_server(created)


async def connect_gmail(connection):
    """Checks the login with Gmail first, so a wrong password fails here and not later in a chat."""
    address = connection["address"]
    password = mailbox.clean_app_password(connection["appPassword"])
    await asyncio.wait_for(asyncio.to_thread(mailbox.check_login, address, password), TOOL_TIMEOUT)

    password_secret = env_secrets.secret_name(GMAIL_NAME, "APP_PASSWORD")
    record = {
        "name": GMAIL_NAME,
        "transport": "stdio",
        "command": sys.executable,
        "args": GMAIL_SERVER_ARGS,
        "env": {
            "GMAIL_ADDRESS": address,
            "GMAIL_APP_PASSWORD": env_secrets.reference(password_secret),
            "PYTHONPATH": str(config.ROOT_DIR),
        },
    }
    created = await save_with_secrets(
        GMAIL_NAME, {password_secret: password}, lambda: mcp_store.create_server(record)
    )
    logger.info("Connected Gmail")
    return public_mcp_server(created)


async def begin_google_calendar_sign_in(connection, redirect_uri):
    """Returns the address to sign in at; the connection is saved once sign-in finishes."""
    if any(existing["name"] == GOOGLE_CALENDAR_NAME for existing in await mcp_store.list_servers()):
        raise DuplicateNameError(GOOGLE_CALENDAR_NAME)
    return calendar_sign_in.begin(connection["clientId"], connection["clientSecret"], redirect_uri)


async def finish_google_calendar_sign_in(state, code):
    client_id, client_secret, refresh_token, account = await calendar_sign_in.finish(state, code)
    secret_name = env_secrets.secret_name(GOOGLE_CALENDAR_NAME, "CLIENT_SECRET")
    token_name = env_secrets.secret_name(GOOGLE_CALENDAR_NAME, "REFRESH_TOKEN")
    record = {
        "name": GOOGLE_CALENDAR_NAME,
        "transport": "stdio",
        "command": sys.executable,
        "args": GOOGLE_CALENDAR_SERVER_ARGS,
        "env": {
            "GOOGLE_CLIENT_ID": client_id,
            "GOOGLE_CLIENT_SECRET": env_secrets.reference(secret_name),
            "GOOGLE_REFRESH_TOKEN": env_secrets.reference(token_name),
            "PYTHONPATH": str(config.ROOT_DIR),
            **({GOOGLE_ACCOUNT_KEY: account} if account else {}),
        },
    }
    created = await save_with_secrets(
        GOOGLE_CALENDAR_NAME,
        {secret_name: client_secret, token_name: refresh_token},
        lambda: mcp_store.create_server(record),
    )
    logger.info("Connected Google Calendar")
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

    async def check_and_create():
        if secrets_to_save:
            await api_client.check_login(record, TOOL_TIMEOUT)
        return await api_store.create_integration(record)

    created = await save_with_secrets(integration["name"], secrets_to_save, check_and_create)
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
    if server["args"] == GMAIL_SERVER_ARGS:
        return {
            "id": server["id"],
            "kind": "mcp",
            "provider": "gmail",
            "name": server["name"],
            "transport": server["transport"],
            "target": server["env"]["GMAIL_ADDRESS"],
            "enabled": server["enabled"],
        }
    if server["args"] == GOOGLE_CALENDAR_SERVER_ARGS:
        return {
            "id": server["id"],
            "kind": "mcp",
            "provider": "google-calendar",
            "name": server["name"],
            "transport": server["transport"],
            "target": server["env"].get(GOOGLE_ACCOUNT_KEY, "Signed in with Google"),
            "enabled": server["enabled"],
        }
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


async def check_mcp_server(server):
    """Listing tools doesn't prove a Gmail login, because its local server only signs in when it reads mail."""
    if server["args"] == GMAIL_SERVER_ARGS:
        environment = env_secrets.resolve_mapping(server["env"])
        await asyncio.to_thread(mailbox.check_login, environment["GMAIL_ADDRESS"], environment["GMAIL_APP_PASSWORD"])
        return
    if server["args"] == GOOGLE_CALENDAR_SERVER_ARGS:
        environment = env_secrets.resolve_mapping(server["env"])
        await asyncio.to_thread(
            calendar_api.get_access_token,
            environment["GOOGLE_CLIENT_ID"],
            environment["GOOGLE_CLIENT_SECRET"],
            environment["GOOGLE_REFRESH_TOKEN"],
        )
        return
    await oauth.refresh_if_needed(server)
    await toolbox.check_connection(server)


async def check_api_integration(integration):
    """An API with no login has nothing to check."""
    if integration["headers"]:
        await api_client.check_login(integration, TOOL_TIMEOUT)


def problem_text(error):
    if isinstance(error, mailbox.GmailLoginError):
        return "Gmail rejected the app password."
    if isinstance(error, (LoginNotConfirmed, McpError, calendar_api.CalendarError)):
        return str(error)
    if isinstance(error, asyncio.TimeoutError):
        return "It didn't answer in time."
    if isinstance(error, (OSError, httpx.HTTPError)):
        return "Couldn't reach it."
    return "Couldn't check this connection."


async def find_problem(kind, integration_id, check):
    """Returns the integration's status. One broken connection must never stop the others being checked."""
    try:
        await asyncio.wait_for(check, HEALTH_CHECK_TIMEOUT)
    except Exception as error:
        logger.warning("Integration %s %s isn't working: %s", kind, integration_id, type(error).__name__)
        return {"kind": kind, "id": integration_id, "problem": problem_text(error)}
    return {"kind": kind, "id": integration_id, "problem": None}


async def check_health():
    """Checks each integration that's turned on. Turned-off ones aren't in use, so they aren't contacted."""
    servers = await mcp_store.list_servers()
    integrations = await api_store.list_integrations()
    checks = [
        *(find_problem("mcp", server["id"], check_mcp_server(server)) for server in servers if server["enabled"]),
        *(
            find_problem("api", integration["id"], check_api_integration(integration))
            for integration in integrations
            if integration["enabled"]
        ),
    ]
    return await asyncio.gather(*checks)


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


def describe_mcp_server(server):
    """Other servers show only their name, because their address or command could contain a key."""
    public = public_mcp_server(server)
    if "provider" in public and "@" in public["target"]:
        return f"{public['name']} ({public['target']})"
    return public["name"]


def describe_connections(mcp_servers, api_integrations):
    """What's connected, in words safe to give the model."""
    return [*map(describe_mcp_server, mcp_servers), *(integration["name"] for integration in api_integrations)]
