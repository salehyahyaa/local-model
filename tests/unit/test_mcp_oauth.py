import asyncio
import base64
import hashlib
import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from src.backend.integrations import env_secrets, mcp_stdio_transport, mcp_store, oauth, service, toolbox
from src.backend.integrations.errors import McpError
from src.backend.integrations.mcp_stdio_transport import build_child_environment

FAKE_STDIO_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "fake_mcp_stdio_server.py"
SERVER_URL = "https://mcp.example.com/mcp"
REDIRECT_URI = "http://localhost:8000/api/integrations/mcp/oauth/callback"
AUTH_METADATA = {
    "authorization_endpoint": "https://auth.example.com/authorize",
    "token_endpoint": "https://auth.example.com/token",
    "registration_endpoint": "https://auth.example.com/register",
}


class FakeServices:
    """A hosted MCP server and its sign-in service, as the spec describes them."""

    def __init__(self, metadata=AUTH_METADATA):
        self.metadata = metadata
        self.token_requests = []

    def __call__(self, request):
        url = str(request.url)
        if url == SERVER_URL:
            challenge = 'Bearer resource_metadata="https://mcp.example.com/resource-info"'
            return httpx.Response(401, headers={"WWW-Authenticate": challenge})
        if url == "https://mcp.example.com/resource-info":
            return httpx.Response(
                200, json={"authorization_servers": ["https://auth.example.com"], "scopes_supported": ["read"]}
            )
        if url == "https://auth.example.com/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=self.metadata)
        if url == AUTH_METADATA["registration_endpoint"]:
            assert json.loads(request.content)["redirect_uris"] == [REDIRECT_URI]
            return httpx.Response(201, json={"client_id": "registered-id"})
        if url == AUTH_METADATA["token_endpoint"]:
            form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
            self.token_requests.append(form)
            return httpx.Response(
                200, json={"access_token": f"access-{len(self.token_requests)}", "refresh_token": "r", "expires_in": 3600}
            )
        return httpx.Response(404)


@pytest.fixture
def services(monkeypatch):
    fake = FakeServices()
    monkeypatch.setattr(oauth, "make_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(oauth, "pending_sign_ins", {})
    monkeypatch.setenv("USE_KEYCHAIN", "0")
    return fake


def begin(client_id="", client_secret=""):
    return asyncio.run(oauth.begin_sign_in("Notes", SERVER_URL, client_id, client_secret, REDIRECT_URI))


def test_sign_in_finds_the_service_registers_and_uses_pkce(services):
    address = urlparse(begin())
    query = {key: values[0] for key, values in parse_qs(address.query).items()}
    assert address.netloc == "auth.example.com"
    assert query["client_id"] == "registered-id"
    assert query["resource"] == SERVER_URL
    assert query["scope"] == "read"
    assert query["code_challenge_method"] == "S256"

    name, url, access_token, saved = asyncio.run(oauth.finish_sign_in(query["state"], "the-code"))
    assert (name, url, access_token) == ("Notes", SERVER_URL, "access-1")

    form = services.token_requests[0]
    assert form["code"] == "the-code"
    assert form["resource"] == SERVER_URL
    digest = hashlib.sha256(form["code_verifier"].encode()).digest()
    assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == query["code_challenge"]
    assert json.loads(saved)["refreshToken"] == "r"


def test_a_sign_in_can_only_be_finished_once(services):
    state = parse_qs(urlparse(begin()).query)["state"][0]
    asyncio.run(oauth.finish_sign_in(state, "code"))
    with pytest.raises(oauth.OAuthError, match="expired"):
        asyncio.run(oauth.finish_sign_in(state, "code"))


def test_unknown_sign_in_is_rejected(services):
    with pytest.raises(oauth.OAuthError, match="expired"):
        asyncio.run(oauth.finish_sign_in("made-up", "code"))


def test_entered_client_id_skips_registration_and_secret_is_sent(services):
    services.metadata = {
        **AUTH_METADATA,
        "registration_endpoint": None,
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    }
    query = parse_qs(urlparse(begin("my-id", "my-secret")).query)
    assert query["client_id"] == ["my-id"]
    asyncio.run(oauth.finish_sign_in(query["state"][0], "code"))
    assert services.token_requests[0]["client_id"] == "my-id"
    assert services.token_requests[0]["client_secret"] == "my-secret"


def test_server_without_registration_asks_for_a_client_id(services):
    services.metadata = {**AUTH_METADATA, "registration_endpoint": None}
    with pytest.raises(oauth.OAuthError, match="client ID"):
        begin()


def test_sign_in_address_must_be_a_web_address(services):
    services.metadata = {**AUTH_METADATA, "authorization_endpoint": "javascript:alert(1)"}
    with pytest.raises(oauth.OAuthError, match="invalid"):
        begin()


def signed_in_server(services, expires_at):
    access_secret, state_secret, headers, environment = oauth.build_secret_references("Notes")
    env_secrets.save_secret(access_secret, "old-access")
    env_secrets.save_secret(
        state_secret,
        json.dumps(
            {
                "tokenEndpoint": AUTH_METADATA["token_endpoint"],
                "clientId": "id",
                "clientSecret": "",
                "authMethod": "none",
                "resource": SERVER_URL,
                "refreshToken": "old-refresh",
                "expiresAt": expires_at,
            }
        ),
    )
    return {"name": "Notes", "transport": "http", "url": SERVER_URL, "headers": headers, "env": environment}


def test_expired_token_is_renewed(services, monkeypatch):
    server = signed_in_server(services, time.time() - 10)
    asyncio.run(oauth.refresh_if_needed(server))
    assert services.token_requests[0]["refresh_token"] == "old-refresh"
    assert toolbox.create_transport(server).headers["Authorization"] == "Bearer access-1"


def test_valid_token_is_left_alone(services):
    server = signed_in_server(services, time.time() + 3600)
    asyncio.run(oauth.refresh_if_needed(server))
    assert services.token_requests == []


def test_servers_without_sign_in_are_left_alone():
    asyncio.run(oauth.refresh_if_needed({"transport": "stdio", "env": {"OAUTH": "not a sign-in"}}))


def stdio_server(*args):
    return {"name": "Fake", "transport": "stdio", "command": sys.executable, "args": list(args), "env": {}}


def test_connection_check_passes_for_a_working_server():
    asyncio.run(toolbox.check_connection(stdio_server(str(FAKE_STDIO_SERVER))))


def test_connection_check_reports_a_command_that_cant_start():
    server = {**stdio_server(), "command": "/no/such/program"}
    with pytest.raises(McpError, match="Could not start"):
        asyncio.run(toolbox.check_connection(server))


def test_failed_connection_saves_nothing(monkeypatch):
    monkeypatch.setenv("USE_KEYCHAIN", "0")

    async def fake_create(record):
        raise AssertionError("must not be saved")

    monkeypatch.setattr(mcp_store, "create_server", fake_create)
    server = {
        "name": "Broken",
        "transport": "stdio",
        "command": "/no/such/program",
        "args": [],
        "env": [{"name": "TOKEN", "value": "abc"}],
    }
    with pytest.raises(McpError):
        asyncio.run(service.add_mcp_server(server))
    assert not env_secrets.secret_exists(env_secrets.secret_name("Broken", "TOKEN"))


def test_local_servers_dont_receive_the_apps_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_PASSWORD", "hidden")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "hidden")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(mcp_stdio_transport, "read_login_shell_path", lambda: "/opt/tools/bin")
    environment = build_child_environment({"TOKEN": "mine"})
    assert "DATABASE_PASSWORD" not in environment
    assert "TELEGRAM_BOT_TOKEN" not in environment
    assert environment["PATH"] == "/opt/tools/bin:/usr/bin"
    assert environment["TOKEN"] == "mine"
    assert environment["DO_NOT_TRACK"] == "1"
