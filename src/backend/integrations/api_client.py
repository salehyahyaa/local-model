import logging
from urllib.parse import quote

import httpx

from src.backend.integrations import env_secrets
from src.backend.integrations.validation import URL_PLACEHOLDER_PATTERN

logger = logging.getLogger(__name__)

METHODS_WITH_BODY = {"POST", "PUT", "PATCH"}


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


async def call_api(integration, arguments, timeout):
    request = build_request(integration, arguments)
    logger.info("Calling %s %s for integration %r", request["method"], request["url"], integration["name"])
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.request(**request)
    return f"HTTP {response.status_code}\n{response.text}"
