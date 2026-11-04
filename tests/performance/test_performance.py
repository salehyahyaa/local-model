"""Load handling, page weight, and staying responsive while an image is being made."""

import asyncio
import re
import threading
import time

import httpx
import pytest

from src.backend.main import app
from src.backend.models.image_generation import routes, store
from tests.helpers import ROOT_DIR, BackgroundServer

FRONTEND_DIR = ROOT_DIR / "src" / "frontend"
STATIC_IMPORT = re.compile(r'^import .*? from "(\.[^"]+)";', re.MULTILINE)

CONCURRENT_CLIENTS = 20
REQUESTS_PER_CLIENT = 10
LOAD_BUDGET_SECONDS = 10
PAGE_WEIGHT_BUDGET_BYTES = 150 * 1024
RESPONSIVE_BUDGET_MS = 500
MIN_RESPONSES_DURING_GENERATION = 5


def startup_scripts():
    """main.js plus everything it imports up front. Code loaded with import() isn't part of startup."""
    pending = [FRONTEND_DIR / "main.js"]
    found = set()
    while pending:
        path = pending.pop().resolve()
        if path not in found:
            found.add(path)
            pending += [path.parent / target for target in STATIC_IMPORT.findall(path.read_text())]
    return found


def test_startup_code_excludes_image_generation():
    folder = FRONTEND_DIR / "models" / "imageGeneration"
    assert not [script for script in startup_scripts() if folder in script.parents]


def test_startup_page_weight_is_within_budget(running_app):
    page = httpx.get(running_app)
    stylesheets = re.findall(r'<link rel="stylesheet" href="/assets/([^"]+)"', page.text)
    total = len(page.content)
    total += sum(len(httpx.get(f"{running_app}/assets/{sheet}").content) for sheet in stylesheets)
    total += sum(script.stat().st_size for script in startup_scripts())
    print(f"Startup page weight: {total / 1024:.1f} KB")
    assert total < PAGE_WEIGHT_BUDGET_BYTES


def test_handles_concurrent_requests(running_app):
    async def client_session(client):
        return [await client.get("/api/health") for _ in range(REQUESTS_PER_CLIENT)]

    async def run():
        async with httpx.AsyncClient(base_url=running_app, timeout=LOAD_BUDGET_SECONDS) as client:
            return await asyncio.gather(*(client_session(client) for _ in range(CONCURRENT_CLIENTS)))

    started = time.perf_counter()
    sessions = asyncio.run(run())
    elapsed = time.perf_counter() - started
    responses = [response for session in sessions for response in session]
    print(f"{len(responses)} requests in {elapsed:.2f} s ({len(responses) / elapsed:.0f} per second)")
    assert all(response.status_code == 200 for response in responses)
    assert elapsed < LOAD_BUDGET_SECONDS


@pytest.fixture
def server_with_slow_worker(tmp_path, monkeypatch):
    """The real route and a real worker process, with a stand-in for the model."""
    model_file = tmp_path / "model.safetensors"
    model_file.touch()

    async def fake_exists(conversation_id):
        return True

    async def fake_save(conversation_id, prompt, input_files, output_files):
        return {"userMessage": {}, "assistantMessage": {"imageFiles": output_files}}

    monkeypatch.setattr(routes, "IMAGE_MODEL_PATH", model_file)
    monkeypatch.setattr(routes, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(routes, "WORKER_MODULE", "tests.fixtures.slow_image_worker")
    monkeypatch.setattr(store, "IMAGE_DIR", tmp_path)
    monkeypatch.setattr(store, "conversation_exists", fake_exists)
    monkeypatch.setattr(store, "save_exchange", fake_save)

    server = BackgroundServer(app)
    server.start()
    yield server.url
    server.stop()


def test_server_stays_responsive_while_making_an_image(server_with_slow_worker):
    result = {}

    def make_image():
        result["response"] = httpx.post(
            f"{server_with_slow_worker}/api/conversations/1/images", json={"prompt": "a cat"}, timeout=30
        )

    generation = threading.Thread(target=make_image)
    generation.start()
    timings = []
    with httpx.Client(base_url=server_with_slow_worker) as client:
        while generation.is_alive():
            started = time.perf_counter()
            assert client.get("/api/health").status_code == 200
            timings.append((time.perf_counter() - started) * 1000)
            time.sleep(0.05)
    generation.join()

    print(f"{len(timings)} requests answered during generation, slowest {max(timings):.1f} ms")
    assert result["response"].status_code == 201
    assert len(timings) >= MIN_RESPONSES_DURING_GENERATION
    assert max(timings) < RESPONSIVE_BUDGET_MS
