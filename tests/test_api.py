from fastapi.testclient import TestClient

from src.backend import llm
from src.backend.main import app

client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_index_serves_chat_page():
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="message-form"' in response.text


def test_static_assets():
    assert client.get("/static/js/main.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_chat_streams_model_output(monkeypatch):
    async def fake_stream_chat(messages):
        assert messages[-1]["content"] == "hi"
        for text_chunk in ["Hel", "lo"]:
            yield text_chunk

    monkeypatch.setattr(llm, "stream_chat", fake_stream_chat)
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 200
    assert response.text == "Hello"


def test_chat_rejects_empty_messages():
    response = client.post("/api/chat", json={"messages": []})
    assert response.status_code == 422


def test_chat_rejects_invalid_role():
    response = client.post("/api/chat", json={"messages": [{"role": "invalid", "content": "x"}]})
    assert response.status_code == 422


def test_chat_rejects_missing_body():
    response = client.post("/api/chat", content="not json")
    assert response.status_code == 422



def test_chat_reports_no_model_connected(monkeypatch):
    async def fake_stream_chat(messages):
        raise llm.ModelUnavailableError("Could not connect to Ollama")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(llm, "stream_chat", fake_stream_chat)
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 503
    assert response.json()["error"] == "No model is connected."


def test_chat_reports_no_model_when_ollama_unreachable(monkeypatch):
    monkeypatch.setattr(llm, "OLLAMA_URL", "http://127.0.0.1:1")
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 503
    assert response.json()["error"] == "No model is connected."
