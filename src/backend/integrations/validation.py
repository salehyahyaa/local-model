import re
import shlex

NAME_MAX_LENGTH = 60
DESCRIPTION_MAX_LENGTH = 1000
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HEADER_NAME_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")
URL_PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def clean_text(value, max_length):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > max_length:
        return None
    return text


def is_http_url(value):
    return isinstance(value, str) and value.startswith(("http://", "https://")) and len(value) <= 2000


AUTH_TYPES = {"none", "apiKey", "basic"}


def validate_auth(body):
    """authType is "none", "apiKey" (link + API key) or "basic" (username + password)."""
    auth_type = body.get("authType") or ("apiKey" if body.get("apiKey") else "none")
    if auth_type not in AUTH_TYPES:
        return None, "Login type must be none, API key, or username and password."
    if auth_type == "none":
        return {"authType": "none"}, None
    if auth_type == "basic":
        username = body.get("username")
        password = body.get("password")
        if not isinstance(username, str) or not username.strip() or ":" in username:
            return None, "Username is required and can't contain a colon."
        if not isinstance(password, str) or not password:
            return None, "Password is required."
        return {"authType": "basic", "username": username.strip(), "password": password}, None

    api_key = body.get("apiKey") or ""
    auth_header = body.get("authHeader") or "Authorization"
    auth_prefix = body.get("authPrefix")
    if auth_prefix is None:
        auth_prefix = "Bearer "
    if not isinstance(api_key, str) or not isinstance(auth_prefix, str) or len(auth_prefix) > 30:
        return None, "Invalid API key settings."
    if not isinstance(auth_header, str) or not HEADER_NAME_PATTERN.match(auth_header):
        return None, "Header name can only contain letters, numbers and dashes."
    if not api_key.strip():
        return None, "API key is required."
    return {"authType": "apiKey", "apiKey": api_key.strip(), "authHeader": auth_header, "authPrefix": auth_prefix}, None


def validate_environment(entries):
    if entries is None:
        return [], None
    if not isinstance(entries, list):
        return None, "Environment variables must be a list."
    environment = []
    seen_names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return None, "Invalid environment variable."
        name = entry.get("name")
        value = entry.get("value")
        if not isinstance(name, str) or not IDENTIFIER_PATTERN.match(name):
            return None, "Environment variable names can only contain letters, numbers and underscores."
        if not isinstance(value, str) or not value:
            return None, f"Environment variable {name} needs a value."
        if name in seen_names:
            return None, f"Environment variable {name} is listed twice."
        seen_names.add(name)
        environment.append({"name": name, "value": value})
    return environment, None


def validate_mcp_server(body):
    if not isinstance(body, dict):
        return None, "Invalid request."
    name = clean_text(body.get("name"), NAME_MAX_LENGTH)
    if name is None:
        return None, f"Name is required (up to {NAME_MAX_LENGTH} characters)."

    transport = body.get("transport")
    if transport == "http":
        url = body.get("url")
        if not is_http_url(url):
            return None, "URL must start with http:// or https://."
        if body.get("authType") == "oauth":
            client_id = body.get("clientId") or ""
            client_secret = body.get("clientSecret") or ""
            if not isinstance(client_id, str) or not isinstance(client_secret, str):
                return None, "Invalid client ID or secret."
            return {
                "name": name,
                "transport": "http",
                "url": url.strip(),
                "authType": "oauth",
                "clientId": client_id.strip(),
                "clientSecret": client_secret.strip(),
            }, None
        auth, error = validate_auth(body)
        if error:
            return None, error
        return {"name": name, "transport": "http", "url": url.strip(), **auth}, None

    if transport == "stdio":
        command = clean_text(body.get("command"), 500)
        if command is None:
            return None, "Command is required."
        arguments_text = body.get("args") or ""
        if not isinstance(arguments_text, str):
            return None, "Arguments must be text."
        try:
            arguments = shlex.split(arguments_text)
            # The form takes one line, like "npx -y some-server"; a path with spaces needs quotes.
            if not arguments:
                command, *arguments = shlex.split(command)
        except ValueError:
            return None, "Arguments have an unclosed quote."
        environment, error = validate_environment(body.get("env"))
        if error:
            return None, error
        return {"name": name, "transport": "stdio", "command": command, "args": arguments, "env": environment}, None

    return None, "Connection type must be http or stdio."


def validate_parameters(entries):
    if entries is None:
        return [], None
    if not isinstance(entries, list):
        return None, "Parameters must be a list."
    parameters = []
    seen_names = set()
    for entry in entries:
        if not isinstance(entry, dict):
            return None, "Invalid parameter."
        name = entry.get("name")
        if not isinstance(name, str) or not IDENTIFIER_PATTERN.match(name):
            return None, "Parameter names can only contain letters, numbers and underscores."
        if name in seen_names:
            return None, f"Parameter {name} is listed twice."
        seen_names.add(name)
        description = entry.get("description") or ""
        if not isinstance(description, str) or len(description) > 300:
            return None, f"Description for {name} is too long."
        parameters.append(
            {"name": name, "description": description.strip(), "required": entry.get("required") is True}
        )
    return parameters, None


def validate_api_integration(body):
    if not isinstance(body, dict):
        return None, "Invalid request."
    name = clean_text(body.get("name"), NAME_MAX_LENGTH)
    if name is None:
        return None, f"Name is required (up to {NAME_MAX_LENGTH} characters)."
    description = clean_text(body.get("description"), DESCRIPTION_MAX_LENGTH)
    if description is None:
        return None, "Describe what this API does so the model knows when to use it."
    method = body.get("method")
    if method not in ALLOWED_METHODS:
        return None, "Method must be GET, POST, PUT, PATCH or DELETE."
    url = body.get("url")
    if not is_http_url(url):
        return None, "URL must start with http:// or https://."
    parameters, error = validate_parameters(body.get("parameters"))
    if error:
        return None, error
    declared_names = {parameter["name"] for parameter in parameters}
    for placeholder in URL_PLACEHOLDER_PATTERN.findall(url):
        if placeholder not in declared_names:
            return None, f"The URL uses {{{placeholder}}} but there is no parameter called {placeholder}."
    auth, error = validate_auth(body)
    if error:
        return None, error
    return {
        "name": name,
        "description": description,
        "method": method,
        "url": url.strip(),
        "parameters": parameters,
        **auth,
    }, None


def validate_google_calendar_connection(body):
    if not isinstance(body, dict):
        return None, "Invalid request."
    client_id = body.get("clientId")
    if not isinstance(client_id, str) or not client_id.strip().endswith(".apps.googleusercontent.com"):
        return None, "Enter the client ID from Google. It ends in .apps.googleusercontent.com."
    client_secret = body.get("clientSecret")
    if not isinstance(client_secret, str) or not client_secret.strip():
        return None, "Enter the client secret from Google."
    return {"clientId": client_id.strip(), "clientSecret": client_secret.strip()}, None


def validate_gmail_connection(body):
    if not isinstance(body, dict):
        return None, "Invalid request."
    address = body.get("address")
    if not isinstance(address, str) or not EMAIL_PATTERN.match(address.strip()):
        return None, "Enter your full Gmail address."
    password = body.get("appPassword")
    if not isinstance(password, str) or not password.strip():
        return None, "Enter your app password."
    return {"address": address.strip(), "appPassword": password}, None


def validate_enabled_change(body):
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        return None
    return body["enabled"]
