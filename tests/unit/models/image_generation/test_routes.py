import base64
import json
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from src.backend.main import app
from src.backend.models.image_generation import routes, store
from tests.helpers import ROOT_DIR

client = TestClient(app)

PROMPT = {"prompt": "a cat"}


async def write_outputs(job):
    for path in job["outputPaths"]:
        with open(path, "wb") as output:
            output.write(b"png")


def encoded(content=b"uploaded"):
    return base64.b64encode(content).decode()


@pytest.fixture
def image_setup(tmp_path, monkeypatch):
    model_file = tmp_path / "model.safetensors"
    model_file.touch()
    saved = []

    async def fake_exists(conversation_id):
        return conversation_id == 1

    async def fake_save(conversation_id, prompt, input_files, output_files):
        saved.append((conversation_id, prompt, input_files, output_files))
        return {"userMessage": {"imageFiles": input_files}, "assistantMessage": {"imageFiles": output_files}}

    monkeypatch.setattr(routes, "IMAGE_MODEL_PATH", model_file)
    monkeypatch.setattr(routes, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(store, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(store, "conversation_exists", fake_exists)
    monkeypatch.setattr(store, "save_exchange", fake_save)
    monkeypatch.setattr(routes, "run_worker", write_outputs)
    return tmp_path, saved


def output_files(directory):
    return sorted(path.name for path in directory.glob("*.png"))


def test_generate_saves_one_image_and_serves_it(image_setup):
    directory, saved = image_setup
    response = client.post("/api/conversations/1/images", json=PROMPT)
    assert response.status_code == 201
    [file_name] = response.json()["assistantMessage"]["imageFiles"]
    assert output_files(directory) == [file_name]
    assert saved[0][:3] == (1, "a cat", [])
    assert client.get(f"/api/images/{file_name}").content == b"png"


def test_each_uploaded_image_gets_its_own_output(image_setup, monkeypatch):
    directory, _ = image_setup
    jobs = []

    async def fake_worker(job):
        jobs.append(job)
        await write_outputs(job)

    monkeypatch.setattr(routes, "run_worker", fake_worker)
    images = [f"data:image/png;base64,{encoded(b'first')}", encoded(b"second")]
    response = client.post("/api/conversations/1/images", json={"prompt": "make it blue", "images": images})
    assert response.status_code == 201
    contents = []
    for path in jobs[0]["inputPaths"]:
        with open(path, "rb") as uploaded:
            contents.append(uploaded.read())
    assert contents == [b"first", b"second"]
    assert len(jobs[0]["outputPaths"]) == 2
    assert len(output_files(directory)) == 4


def test_allows_twenty_images(image_setup):
    body = {"prompt": "x", "images": [encoded()] * routes.MAX_IMAGES_PER_REQUEST}
    response = client.post("/api/conversations/1/images", json=body)
    assert response.status_code == 201
    assert len(response.json()["assistantMessage"]["imageFiles"]) == 20


def test_rejects_more_than_twenty_images(image_setup):
    directory, saved = image_setup
    body = {"prompt": "x", "images": [encoded()] * (routes.MAX_IMAGES_PER_REQUEST + 1)}
    response = client.post("/api/conversations/1/images", json=body)
    assert response.status_code == 422
    assert response.json()["error"] == "You can send up to 20 images in a message."
    assert output_files(directory) == []
    assert saved == []


def test_rejects_images_over_the_total_size(image_setup, monkeypatch):
    monkeypatch.setattr(routes, "MAX_TOTAL_IMAGE_BYTES", 10)
    body = {"prompt": "x", "images": [encoded(b"123456"), encoded(b"123456")]}
    response = client.post("/api/conversations/1/images", json=body)
    assert response.status_code == 422
    assert "100 MB" in response.json()["error"]


def test_rejects_oversized_request_before_reading_it(image_setup):
    too_large = str(routes.MAX_TOTAL_IMAGE_BYTES * 2)
    request = type("FakeRequest", (), {"headers": {"content-length": too_large}})
    assert routes.is_request_too_large(request)


@pytest.mark.parametrize(
    "body",
    [{}, {"prompt": "  "}, {"prompt": 5}, {"prompt": "x" * 2001}, {"prompt": "x", "images": ["not base64!"]},
     {"prompt": "x", "images": [5]}, {"prompt": "x", "images": "text"}],
)
def test_rejects_invalid_requests(image_setup, body):
    assert client.post("/api/conversations/1/images", json=body).status_code == 422


def test_missing_conversation_returns_404(image_setup):
    assert client.post("/api/conversations/2/images", json=PROMPT).status_code == 404


def test_missing_model_file_returns_503(image_setup, monkeypatch, tmp_path):
    monkeypatch.setattr(routes, "IMAGE_MODEL_PATH", tmp_path / "gone.safetensors")
    response = client.post("/api/conversations/1/images", json=PROMPT)
    assert response.status_code == 503
    assert response.json()["error"] == "The image model file was not found."


def test_failed_generation_removes_files(image_setup, monkeypatch):
    directory, saved = image_setup

    async def failing_worker(job):
        raise routes.GenerationFailedError("out of memory")

    monkeypatch.setattr(routes, "run_worker", failing_worker)
    response = client.post("/api/conversations/1/images", json={"prompt": "x", "images": [encoded()]})
    assert response.status_code == 502
    assert output_files(directory) == []
    assert saved == []


def test_unreadable_upload_returns_422_and_removes_files(image_setup, monkeypatch):
    directory, _ = image_setup

    async def rejecting_worker(job):
        raise routes.InvalidImageError

    monkeypatch.setattr(routes, "run_worker", rejecting_worker)
    response = client.post("/api/conversations/1/images", json={"prompt": "x", "images": [encoded()]})
    assert response.status_code == 422
    assert output_files(directory) == []


@pytest.mark.parametrize("file_name", ["..%2F..%2Fsecret.png", "notes.txt", "abc.png"])
def test_get_image_rejects_other_file_names(image_setup, file_name):
    assert client.get(f"/api/images/{file_name}").status_code == 404


def test_worker_rejects_unreadable_image_without_loading_the_model(tmp_path):
    bad_image = tmp_path / "bad.png"
    bad_image.write_bytes(b"not an image")
    job = {"modelPath": "unused", "prompt": "x", "inputPaths": [str(bad_image)], "outputPaths": ["unused"]}
    result = subprocess.run(
        [sys.executable, "-m", routes.WORKER_MODULE], input=json.dumps(job), text=True, cwd=ROOT_DIR, capture_output=True
    )
    assert result.returncode == routes.EXIT_INVALID_IMAGE
