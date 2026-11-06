import logging
from urllib.parse import quote

import httpx

from src.backend.integrations import env_secrets
from src.backend.integrations.errors import LoginNotConfirmed
from src.backend.integrations.validation import URL_PLACEHOLDER_PATTERN

logger = logging.getLogger(__name__)

METHODS_WITH_BODY = {"POST", "PUT", "PATCH"}
LOGIN_REJECTED = {401, 403}
# The service looked at the request itself (missing details, too many requests), which normally means the login passed.
ANSWERED_AFTER_LOGIN = {400, 422, 429}


def build_request(integration, arguments):
    declared_names = {parameter["name"] for parameter in integration["parameters"]}
    values = {name: value for name, value in arguments.items() if name in declared_names}
    path_names = set(URL_PLACEHOLDER_PATTERN.findall(integration["url"]))

    url = URL_PLACEHOLDER_PATTERN.sub(
        lambda match: quote(str(values.get(match.group(1), "")), safe=""), integration["url"]
    )
    remaining_values = {name: value for name, value in values.items() if name not in path_names}
    headers = env_secrets.resolve_mapping(integration["headers"])

    request = {"method": integration["method"], "url": url, "headers": headers}
    if integration["method"] in METHODS_WITH_BODY:
        request["json"] = remaining_values
    else:
        request["params"] = remaining_values
    return request


async def check_login(integration, timeout, transport=None):
    """Raises LoginNotConfirmed unless the service accepts the login. Only GET or HEAD, so nothing real ever happens."""
    request = build_request(integration, {})
    method = "GET" if integration["method"] == "GET" else "HEAD"
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.request(method, request["url"], headers=request["headers"])
    except httpx.HTTPError as error:
        raise LoginNotConfirmed("Couldn't reach that service to check the login, so it wasn't saved.") from error
    status = response.status_code
    if status in LOGIN_REJECTED:
        raise LoginNotConfirmed(f"That service rejected the login (HTTP {status}). Check the key and try again.")
    if not (response.is_success or status in ANSWERED_AFTER_LOGIN):
        raise LoginNotConfirmed(f"Couldn't confirm the login (HTTP {status}), so it wasn't saved.")


async def call_api(integration, arguments, timeout):
    request = build_request(integration, arguments)
    logger.info("Calling %s %s for integration %r", request["method"], request["url"], integration["name"])
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(**request)
    return f"HTTP {response.status_code}\n{response.text}"
