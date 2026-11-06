"""OAuth sign-in for hosted MCP servers, written directly against the MCP authorization spec with plain HTTP calls."""

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from urllib.parse import urlencode, urlparse

import httpx

from src.backend.config import TOOL_TIMEOUT
from src.backend.integrations import env_secrets
from src.backend.integrations.errors import McpError
from src.backend.integrations.mcp_client import CLIENT_INFO, PROTOCOL_VERSION
from src.backend.integrations.validation import is_http_url

logger = logging.getLogger(__name__)

STATE_ENV_KEY = "OAUTH"
PENDING_LIFETIME_SECONDS = 600
REFRESH_MARGIN_SECONDS = 60
RESOURCE_METADATA_PATTERN = re.compile(r'resource_metadata="([^"]+)"')

pending_sign_ins = {}
refresh_lock = asyncio.Lock()


class OAuthError(Exception):
    """Sign-in couldn't be completed; the message is safe to show the user."""


def make_client():
    return httpx.AsyncClient(timeout=TOOL_TIMEOUT, follow_redirects=True)


def split_url(url):
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}", parts.path.rstrip("/")


def protected_resource_urls(server_url, challenge):
    origin, path = split_url(server_url)
    match = RESOURCE_METADATA_PATTERN.search(challenge)
    urls = [match[1]] if match else []
    if path:
        urls.append(f"{origin}/.well-known/oauth-protected-resource{path}")
    urls.append(f"{origin}/.well-known/oauth-protected-resource")
    return urls


def authorization_server_urls(issuer):
    origin, path = split_url(issuer)
    if path:
        return [
            f"{origin}/.well-known/oauth-authorization-server{path}",
            f"{origin}/.well-known/openid-configuration{path}",
            f"{origin}{path}/.well-known/openid-configuration",
        ]
    return [f"{origin}/.well-known/oauth-authorization-server", f"{origin}/.well-known/openid-configuration"]


async def first_json(client, urls):
    for url in urls:
        try:
            response = await client.get(url, headers={"Accept": "application/json"})
            if response.status_code == 200 and isinstance(response.json(), dict):
                return response.json()
        except (httpx.HTTPError, ValueError):
            logger.debug("No OAuth metadata at %s", url)
    return None


async def read_challenge(client, server_url):
    """Asks the server to start a session; a server that wants a login says where to sign in on its 401."""
    message = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
    }
    try:
        response = await client.post(
            server_url, json=message, headers={"Accept": "application/json, text/event-stream"}
        )
    except httpx.HTTPError:
        return ""
    return response.headers.get("www-authenticate", "")


async def discover(client, server_url):
    challenge = await read_challenge(client, server_url)
    resource = await first_json(client, protected_resource_urls(server_url, challenge)) or {}
    origin, _ = split_url(server_url)
    issuer = (resource.get("authorization_servers") or [origin])[0]
    metadata = await first_json(client, authorization_server_urls(issuer))
    if metadata is None:
        raise OAuthError("This server doesn't offer sign-in. Try a different login type.")
    # These addresses come from the server and end up in a link and in requests, so they must be plain web addresses.
    if not is_http_url(metadata.get("authorization_endpoint")) or not is_http_url(metadata.get("token_endpoint")):
        raise OAuthError("This server's sign-in settings are invalid.")
    return resource, metadata


async def register_client(client, metadata, redirect_uri):
    endpoint = metadata.get("registration_endpoint")
    if not is_http_url(endpoint):
        raise OAuthError("This server needs a client ID. Create one with the service, then enter it here.")
    try:
        response = await client.post(
            endpoint,
            json={
                "client_name": CLIENT_INFO["name"],
                "redirect_uris": [redirect_uri],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        registered = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise OAuthError("This server refused to register the app for sign-in.") from error
    if response.status_code >= 400 or not registered.get("client_id"):
        raise OAuthError("This server refused to register the app for sign-in.")
    return registered


def pick_auth_method(metadata, registered):
    if registered.get("token_endpoint_auth_method"):
        return registered["token_endpoint_auth_method"]
    supported = metadata.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    return "client_secret_post" if "client_secret_post" in supported else "client_secret_basic"


def forget_expired_sign_ins():
    cutoff = time.time() - PENDING_LIFETIME_SECONDS
    for state in [state for state, pending in pending_sign_ins.items() if pending["startedAt"] < cutoff]:
        del pending_sign_ins[state]


async def begin_sign_in(name, server_url, client_id, client_secret, redirect_uri):
    """Returns the address the user signs in at. Raises OAuthError."""
    async with make_client() as client:
        resource, metadata = await discover(client, server_url)
        registered = {}
        if not client_id:
            registered = await register_client(client, metadata, redirect_uri)

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(32)
    resolved_client_id = client_id or registered["client_id"]

    forget_expired_sign_ins()
    pending_sign_ins[state] = {
        "name": name,
        "url": server_url,
        "redirectUri": redirect_uri,
        "verifier": verifier,
        "startedAt": time.time(),
        "tokenEndpoint": metadata["token_endpoint"],
        "clientId": resolved_client_id,
        "clientSecret": client_secret or registered.get("client_secret", ""),
        "authMethod": pick_auth_method(metadata, registered),
    }

    query = {
        "response_type": "code",
        "client_id": resolved_client_id,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": server_url,
    }
    scopes = resource.get("scopes_supported")
    if scopes:
        query["scope"] = " ".join(scopes)
    endpoint = metadata["authorization_endpoint"]
    return f"{endpoint}{'&' if '?' in endpoint else '?'}{urlencode(query)}"


async def request_tokens(settings, grant):
    form = {**grant, "client_id": settings["clientId"], "resource": settings["resource"]}
    basic_auth = None
    if settings["clientSecret"]:
        if settings["authMethod"] == "client_secret_basic":
            basic_auth = (settings["clientId"], settings["clientSecret"])
        else:
            form["client_secret"] = settings["clientSecret"]
    try:
        async with make_client() as client:
            response = await client.post(
                settings["tokenEndpoint"], data=form, headers={"Accept": "application/json"}, auth=basic_auth
            )
        tokens = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise OAuthError("Couldn't reach the server to finish signing in.") from error
    if response.status_code >= 400 or not tokens.get("access_token"):
        raise OAuthError("The server refused the sign-in.")
    return tokens


def build_saved_state(settings, tokens):
    expires_in = tokens.get("expires_in")
    return {
        "tokenEndpoint": settings["tokenEndpoint"],
        "clientId": settings["clientId"],
        "clientSecret": settings["clientSecret"],
        "authMethod": settings["authMethod"],
        "resource": settings["resource"],
        "refreshToken": tokens.get("refresh_token") or settings.get("refreshToken", ""),
        "expiresAt": time.time() + expires_in if isinstance(expires_in, (int, float)) else None,
    }


async def finish_sign_in(state, code):
    """Returns (name, url, access token, JSON to save). Raises OAuthError."""
    forget_expired_sign_ins()
    pending = pending_sign_ins.pop(state, None)
    if pending is None:
        raise OAuthError("This sign-in has expired. Add the integration again.")
    settings = {**pending, "resource": pending["url"]}
    tokens = await request_tokens(
        settings,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending["redirectUri"],
            "code_verifier": pending["verifier"],
        },
    )
    return pending["name"], pending["url"], tokens["access_token"], json.dumps(build_saved_state(settings, tokens))


def build_secret_references(name):
    """Returns the secret names for a server's access token and sign-in settings, and the server fields that use them."""
    access_secret = env_secrets.secret_name(name, "OAUTH_ACCESS_TOKEN")
    state_secret = env_secrets.secret_name(name, "OAUTH_STATE")
    headers = {"Authorization": "Bearer " + env_secrets.reference(access_secret)}
    environment = {STATE_ENV_KEY: env_secrets.reference(state_secret)}
    return access_secret, state_secret, headers, environment


async def refresh_if_needed(server):
    """Renews a signed-in server's access token shortly before it expires. Raises McpError if that fails."""
    state_reference = (server.get("env") or {}).get(STATE_ENV_KEY)
    if server["transport"] != "http" or not state_reference:
        return
    # One at a time, since some servers cancel a refresh token the moment it's used.
    async with refresh_lock:
        try:
            saved = json.loads(env_secrets.resolve(state_reference))
        except ValueError as error:
            raise McpError("Its sign-in is missing. Remove it and add it again.") from error
        if not saved["expiresAt"] or saved["expiresAt"] > time.time() + REFRESH_MARGIN_SECONDS:
            return
        if not saved["refreshToken"]:
            raise McpError("Its sign-in has expired. Remove it and add it again.")
        try:
            tokens = await request_tokens(saved, {"grant_type": "refresh_token", "refresh_token": saved["refreshToken"]})
        except OAuthError as error:
            raise McpError("Its sign-in has expired. Remove it and add it again.") from error

        access_secret, state_secret, _, _ = build_secret_references(server["name"])
        env_secrets.save_secret(access_secret, tokens["access_token"])
        env_secrets.save_secret(state_secret, json.dumps(build_saved_state(saved, tokens)))
        logger.info("Renewed the sign-in for MCP server %r", server["name"])
