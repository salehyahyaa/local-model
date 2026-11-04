import re

import httpx

from tests.conftest import TEST_DATABASE_URL
from tests.helpers import ROOT_DIR


def test_health(running_app):
    response = httpx.get(f"{running_app}/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_page_and_every_script_load(running_app):
    page = httpx.get(running_app)
    assert page.status_code == 200
    assert 'id="message-form"' in page.text

    frontend_dir = ROOT_DIR / "src" / "frontend"
    for script in frontend_dir.rglob("*.js"):
        path = script.relative_to(frontend_dir).as_posix()
        assert httpx.get(f"{running_app}/assets/{path}").status_code == 200, path
    for stylesheet_or_image in re.findall(r'(?:href|src)="/assets/([^"]+)"', page.text):
        assert httpx.get(f"{running_app}/assets/{stylesheet_or_image}").status_code == 200, stylesheet_or_image


def test_chat_without_model_reports_cleanly(running_app):
    response = httpx.post(f"{running_app}/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 503
    assert response.json() == {"error": "No model is connected."}


def test_saved_state_endpoint(running_app):
    response = httpx.get(f"{running_app}/api/state")
    if TEST_DATABASE_URL:
        assert response.status_code == 200
        assert "conversations" in response.json()
    else:
        assert response.status_code == 503


def test_integrations_endpoint(running_app):
    response = httpx.get(f"{running_app}/api/integrations")
    if TEST_DATABASE_URL:
        assert response.status_code == 200
        assert response.json() == {"mcpServers": [], "apiIntegrations": []}
    else:
        assert response.status_code == 503
