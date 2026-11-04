import asyncio

from src.backend.integrations import api_client


def test_call_api_sends_path_query_and_key(fake_http_services, monkeypatch):
    monkeypatch.setenv("INTEGRATION_WEATHER_API_KEY", "weather-key")
    integration = {
        "name": "Weather",
        "method": "GET",
        "url": f"{fake_http_services}/weather/{{city}}",
        "parameters": [
            {"name": "city", "description": "", "required": True},
            {"name": "units", "description": "", "required": False},
        ],
        "headers": {"X-Api-Key": "${INTEGRATION_WEATHER_API_KEY}"},
    }
    result = asyncio.run(api_client.call_api(integration, {"city": "Oslo", "units": "imperial"}, 5))
    assert result.startswith("HTTP 200")
    assert '"city":"Oslo"' in result
    assert '"units":"imperial"' in result


def test_call_api_reports_http_errors(fake_http_services):
    integration = {
        "name": "Weather",
        "method": "GET",
        "url": f"{fake_http_services}/weather/Oslo",
        "parameters": [],
        "headers": {},
    }
    result = asyncio.run(api_client.call_api(integration, {}, 5))
    assert result.startswith("HTTP 401")
