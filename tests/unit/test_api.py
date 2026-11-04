import asyncio
import json

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from src.backend import db, store, stt
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
    assert client.get("/assets/main.js").status_code == 200
    assert client.get("/assets/base.css").status_code == 200
    assert client.get("/assets/models/imageGeneration/view.js").status_code == 200
    assert client.get("/assets/chat/attachment.html").status_code == 200


def test_static_files_are_revalidated_by_browsers():
    assert client.get("/assets/main.js").headers["cache-control"] == "no-cache"


def test_index_includes_every_html_piece():
    page = client.get("/").text
    assert "<!-- include" not in page
    for element_id in ("sidebar", "model-menu", "integration-dialog", "voice-orb"):
        assert f'id="{element_id}"' in page


def test_index_does_not_load_image_generation_until_selected():
    assert "imageGeneration" not in client.get("/").text


def test_chat_rejects_empty_messages():
    response = client.post("/api/chat", json={"messages": []})
    assert response.status_code == 422


def test_chat_rejects_invalid_role():
    response = client.post("/api/chat", json={"messages": [{"role": "invalid", "content": "x"}]})
    assert response.status_code == 422


def test_chat_rejects_missing_body():
    response = client.post("/api/chat", content="not json")
    assert response.status_code == 422


def deepgram_result(transcript, is_final):
    alternatives = [{"transcript": transcript}]
    return json.dumps({"type": "Results", "is_final": is_final, "channel": {"alternatives": alternatives}})


class FakeDeepgram:
    """Answers audio with a partial transcript, and CloseStream with the final one, then hangs up."""

    def __init__(self):
        self.received = []
        self.replies = asyncio.Queue()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *error):
        return False

    async def send(self, data):
        self.received.append(data)
        if data == stt.CLOSE_STREAM_MESSAGE:
            await self.replies.put(json.dumps({"type": "Metadata"}))
            await self.replies.put(deepgram_result("hello there.", True))
            await self.replies.put(None)
        else:
            await self.replies.put(deepgram_result("hello", False))

    async def close(self):
        await self.replies.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        reply = await self.replies.get()
        if reply is None:
            raise StopAsyncIteration
        return reply


def use_fake_deepgram(monkeypatch):
    deepgram = FakeDeepgram()
    connections = []

    def fake_connect(url, additional_headers, open_timeout):
        connections.append((url, additional_headers))
        return deepgram

    monkeypatch.setattr(stt, "DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(stt, "connect", fake_connect)
    return deepgram, connections


def test_transcribe_stream_sends_words_as_they_are_heard(monkeypatch):
    deepgram, connections = use_fake_deepgram(monkeypatch)
    with client.websocket_connect("/api/transcribe/stream") as websocket:
        websocket.send_bytes(b"\x01\x02")
        assert websocket.receive_json() == {"text": "hello"}
        websocket.send_text(stt.FINISH_MESSAGE)
        assert websocket.receive_json() == {"text": "hello there."}
        assert websocket.receive_json() == {"done": True, "text": "hello there."}

    assert deepgram.received == [b"\x01\x02", stt.CLOSE_STREAM_MESSAGE]
    url, headers = connections[0]
    assert "encoding=linear16" in url and "sample_rate=16000" in url and "interim_results=true" in url
    assert headers == {"Authorization": "Token test-key"}


def test_transcribe_stream_stops_sending_past_the_size_limit(monkeypatch):
    deepgram, _ = use_fake_deepgram(monkeypatch)
    monkeypatch.setattr(stt, "MAX_AUDIO_BYTES", 2)
    with client.websocket_connect("/api/transcribe/stream") as websocket:
        websocket.send_bytes(b"\x01\x02\x03")
        assert websocket.receive_json() == {"text": "hello there."}
        assert websocket.receive_json() == {"done": True, "text": "hello there."}

    assert deepgram.received == [stt.CLOSE_STREAM_MESSAGE]


def test_transcribe_stream_without_key_reports_it(monkeypatch):
    monkeypatch.setattr(stt, "DEEPGRAM_API_KEY", "")
    with client.websocket_connect("/api/transcribe/stream") as websocket:
        assert websocket.receive_json() == {"error": "Speech-to-text is not configured."}


def test_transcribe_stream_reports_a_failed_connection(monkeypatch):
    def failing_connect(url, additional_headers, open_timeout):
        raise OSError("no network")

    monkeypatch.setattr(stt, "DEEPGRAM_API_KEY", "test-key")
    monkeypatch.setattr(stt, "connect", failing_connect)
    with client.websocket_connect("/api/transcribe/stream") as websocket:
        assert websocket.receive_json() == {"error": "The transcription request failed."}


def test_transcribe_stream_rejects_other_websites(monkeypatch):
    use_fake_deepgram(monkeypatch)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/transcribe/stream", headers={"Origin": "https://evil.example"}):
            pass


def test_transcribe_stream_accepts_its_own_page(monkeypatch):
    monkeypatch.setattr(stt, "DEEPGRAM_API_KEY", "")
    with client.websocket_connect("/api/transcribe/stream", headers={"Origin": "http://testserver"}) as websocket:
        assert "error" in websocket.receive_json()


def test_state_without_database_returns_503(monkeypatch):
    monkeypatch.setattr(db, "pool", None)
    response = client.get("/api/state")
    assert response.status_code == 503


def test_rename_conversation(monkeypatch):
    calls = []

    async def fake_update(conversation_id, changes):
        calls.append((conversation_id, changes))
        return True

    monkeypatch.setattr(store, "update_conversation", fake_update)
    response = client.patch("/api/conversations/7", json={"title": "  Trip plans  "})
    assert response.status_code == 200
    assert calls == [(7, {"title": "Trip plans"})]


def test_update_conversation_rejects_unknown_fields():
    response = client.patch("/api/conversations/7", json={"user_id": 2})
    assert response.status_code == 422


def test_update_missing_conversation_returns_404(monkeypatch):
    async def fake_update(conversation_id, changes):
        return False

    monkeypatch.setattr(store, "update_conversation", fake_update)
    response = client.patch("/api/conversations/999", json={"isPinned": True})
    assert response.status_code == 404


def test_add_message_rejects_bad_role():
    response = client.post("/api/conversations/1/messages", json={"role": "admin", "content": "hi"})
    assert response.status_code == 422


def test_add_message_saves_model(monkeypatch):
    calls = []

    async def fake_add_message(conversation_id, role, content, model=None):
        calls.append((conversation_id, role, content, model))
        return 7

    monkeypatch.setattr(store, "add_message", fake_add_message)
    with_model = {"role": "user", "content": "hi", "model": "image-generation"}
    assert client.post("/api/conversations/1/messages", json=with_model).status_code == 201
    assert client.post("/api/conversations/1/messages", json={"role": "user", "content": "hi"}).status_code == 201
    assert calls == [(1, "user", "hi", "image-generation"), (1, "user", "hi", None)]


def test_add_message_rejects_invalid_model():
    response = client.post("/api/conversations/1/messages", json={"role": "user", "content": "hi", "model": 5})
    assert response.status_code == 422


def test_settings_saves_theme(monkeypatch):
    calls = []

    async def fake_update(changes):
        calls.append(changes)
        return True

    monkeypatch.setattr(store, "update_settings", fake_update)
    assert client.patch("/api/settings", json={"theme": "light"}).status_code == 200
    assert client.patch("/api/settings", json={"theme": "blue"}).status_code == 422
    assert calls == [{"theme": "light"}]


def test_settings_saves_selected_model(monkeypatch):
    calls = []

    async def fake_update(changes):
        calls.append(changes)
        return True

    monkeypatch.setattr(store, "update_settings", fake_update)
    assert client.patch("/api/settings", json={"selectedModel": "image-generation"}).status_code == 200
    assert client.patch("/api/settings", json={"selectedModel": ""}).status_code == 422
    assert calls == [{"selectedModel": "image-generation"}]


def test_chat_reports_no_model_connected():
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 503
    assert response.json() == {"error": "No model is connected."}


def test_models_list_is_empty():
    assert client.get("/api/models").json() == {"models": [], "defaultModel": None}
