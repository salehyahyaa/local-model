from fastapi.testclient import TestClient

from src.backend import llm
from src.backend.main import app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_index_serves_chat_page():
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="composer"' in res.text


def test_static_assets():
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200


def test_chat_streams_model_output(monkeypatch):
    async def fake_stream(messages):
        assert messages[-1]["content"] == "hi"
        for chunk in ["Hel", "lo"]:
            yield chunk

    monkeypatch.setattr(llm, "stream_chat", fake_stream)
    res = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 200
    assert res.text == "Hello"


def test_chat_rejects_empty_messages():
    res = client.post("/api/chat", json={"messages": []})
    assert res.status_code == 422


def test_chat_rejects_bad_role():
    res = client.post("/api/chat", json={"messages": [{"role": "hacker", "content": "x"}]})
    assert res.status_code == 422
