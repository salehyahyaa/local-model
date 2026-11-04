from src.backend.integrations.api_client import build_request


def make_integration(**changes):
    integration = {
        "name": "Weather",
        "method": "GET",
        "url": "https://api.example.com/weather/{city}",
        "parameters": [
            {"name": "city", "description": "", "required": True},
            {"name": "units", "description": "", "required": False},
        ],
        "headers": {"Authorization": "Bearer ${INTEGRATION_WEATHER_API_KEY}"},
    }
    integration.update(changes)
    return integration


def test_get_request_fills_path_and_query(monkeypatch):
    monkeypatch.setenv("INTEGRATION_WEATHER_API_KEY", "k3y")
    request = build_request(make_integration(), {"city": "New York", "units": "metric", "ignored": "x"})
    assert request["url"] == "https://api.example.com/weather/New%20York"
    assert request["params"] == {"units": "metric"}
    assert request["headers"] == {"Authorization": "Bearer k3y"}
    assert "json" not in request


def test_post_request_sends_json_body():
    request = build_request(make_integration(method="POST", url="https://api.example.com/weather"), {"city": "Paris"})
    assert request["json"] == {"city": "Paris"}
    assert "params" not in request


def test_path_values_cannot_escape_the_path():
    request = build_request(make_integration(), {"city": "../admin"})
    assert request["url"] == "https://api.example.com/weather/..%2Fadmin"
