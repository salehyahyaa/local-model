from src.backend.integrations.validation import (
    validate_api_integration,
    validate_enabled_change,
    validate_mcp_server,
)


def valid_api_body(**changes):
    body = {
        "name": "Weather",
        "description": "Gets the weather for a city",
        "method": "GET",
        "url": "https://api.example.com/weather/{city}",
        "parameters": [{"name": "city", "description": "City name", "required": True}],
        "apiKey": "secret-key",
    }
    body.update(changes)
    return body


def test_http_mcp_server_uses_default_auth_settings():
    server, error = validate_mcp_server({"name": " GitHub ", "transport": "http", "url": "https://mcp.example.com"})
    assert error is None
    assert server == {
        "name": "GitHub",
        "transport": "http",
        "url": "https://mcp.example.com",
        "authType": "none",
    }


def test_stdio_mcp_server_splits_arguments_and_reads_environment():
    server, error = validate_mcp_server(
        {
            "name": "Files",
            "transport": "stdio",
            "command": "npx",
            "args": '-y "@scope/server files" /tmp',
            "env": [{"name": "TOKEN", "value": "abc"}],
        }
    )
    assert error is None
    assert server["args"] == ["-y", "@scope/server files", "/tmp"]
    assert server["env"] == [{"name": "TOKEN", "value": "abc"}]


def test_stdio_mcp_server_accepts_the_whole_command_on_one_line():
    server, error = validate_mcp_server({"name": "Files", "transport": "stdio", "command": 'npx -y "my server"'})
    assert error is None
    assert server["command"] == "npx"
    assert server["args"] == ["-y", "my server"]


def test_http_mcp_server_with_sign_in():
    server, error = validate_mcp_server(
        {"name": "Notes", "transport": "http", "url": "https://x.com/mcp", "authType": "oauth", "clientId": " id "}
    )
    assert error is None
    assert server["authType"] == "oauth"
    assert server["clientId"] == "id"
    assert server["clientSecret"] == ""


def test_mcp_server_requires_name():
    _, error = validate_mcp_server({"name": "  ", "transport": "http", "url": "https://x.com"})
    assert "Name" in error


def test_mcp_server_rejects_non_http_url():
    _, error = validate_mcp_server({"name": "x", "transport": "http", "url": "ftp://x.com"})
    assert "URL" in error


def test_mcp_server_rejects_unknown_transport():
    _, error = validate_mcp_server({"name": "x", "transport": "carrier-pigeon"})
    assert "Connection type" in error


def test_mcp_server_rejects_unclosed_quote_in_arguments():
    _, error = validate_mcp_server({"name": "x", "transport": "stdio", "command": "run", "args": '"oops'})
    assert "quote" in error


def test_mcp_server_rejects_bad_environment_names():
    _, error = validate_mcp_server(
        {"name": "x", "transport": "stdio", "command": "run", "env": [{"name": "BAD NAME", "value": "1"}]}
    )
    assert "Environment variable names" in error


def test_mcp_server_rejects_empty_environment_value():
    _, error = validate_mcp_server(
        {"name": "x", "transport": "stdio", "command": "run", "env": [{"name": "TOKEN", "value": ""}]}
    )
    assert "needs a value" in error


def test_mcp_server_rejects_bad_header_name():
    _, error = validate_mcp_server(
        {"name": "x", "transport": "http", "url": "https://x.com", "authType": "apiKey", "apiKey": "k",
         "authHeader": "Bad Header"}
    )
    assert "Header name" in error


def test_valid_api_integration():
    integration, error = validate_api_integration(valid_api_body())
    assert error is None
    assert integration["parameters"] == [{"name": "city", "description": "City name", "required": True}]
    assert integration["apiKey"] == "secret-key"


def test_api_integration_requires_description():
    _, error = validate_api_integration(valid_api_body(description=""))
    assert "Describe" in error


def test_api_integration_rejects_unknown_method():
    _, error = validate_api_integration(valid_api_body(method="FETCH"))
    assert "Method" in error


def test_api_integration_rejects_undeclared_url_placeholder():
    _, error = validate_api_integration(valid_api_body(url="https://api.example.com/{country}/{city}"))
    assert "{country}" in error


def test_api_integration_rejects_duplicate_parameters():
    parameters = [{"name": "city"}, {"name": "city"}]
    _, error = validate_api_integration(valid_api_body(parameters=parameters))
    assert "twice" in error


def test_validate_enabled_change():
    assert validate_enabled_change({"enabled": False}) is False
    assert validate_enabled_change({"enabled": "yes"}) is None
    assert validate_enabled_change(None) is None


def test_basic_auth_needs_username_and_password():
    base = {"name": "x", "transport": "http", "url": "https://x.com", "authType": "basic"}
    _, error = validate_mcp_server({**base, "password": "p"})
    assert "Username" in error
    _, error = validate_mcp_server({**base, "username": "u"})
    assert "Password" in error
    server, error = validate_mcp_server({**base, "username": " u ", "password": "p"})
    assert error is None
    assert server["authType"] == "basic" and server["username"] == "u" and server["password"] == "p"


def test_api_key_login_needs_a_key():
    _, error = validate_mcp_server({"name": "x", "transport": "http", "url": "https://x.com", "authType": "apiKey"})
    assert "API key is required" in error
