"""The image model must only use the machine's resources while it's making an image."""

import subprocess
import sys
import time

import httpx
import pytest

from tests.fixtures.slow_image_worker import PID_FILE_ENV
from tests.helpers import ROOT_DIR
from tests.performance.test_performance import server_with_slow_worker  # noqa: F401


def is_running(process_id):
    # A killed child that hasn't been collected yet still exists, so ask for its state too.
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(process_id)], capture_output=True, text=True)
    return bool(result.stdout.strip()) and not result.stdout.strip().startswith("Z")


def wait_until(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.1)
    return False


def test_starting_the_app_does_not_load_the_model_libraries():
    code = (
        "import sys; import src.backend.main; "
        "print([name for name in ('torch', 'diffusers') if name in sys.modules])"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT_DIR, capture_output=True, text=True, check=True)
    assert result.stdout.strip().splitlines()[-1] == "[]"


@pytest.fixture
def pid_file(tmp_path, monkeypatch):
    path = tmp_path / "worker.pid"
    monkeypatch.setenv(PID_FILE_ENV, str(path))
    return path


def test_worker_exits_after_making_an_image(server_with_slow_worker, pid_file):  # noqa: F811
    response = httpx.post(f"{server_with_slow_worker}/api/conversations/1/images", json={"prompt": "x"}, timeout=30)
    assert response.status_code == 201
    assert wait_until(lambda: not is_running(pid_file.read_text()))


def test_closing_the_browser_stops_the_model(server_with_slow_worker, pid_file):  # noqa: F811
    with pytest.raises(httpx.TimeoutException):
        # Giving up early closes the connection, the same as closing the tab.
        httpx.post(f"{server_with_slow_worker}/api/conversations/1/images", json={"prompt": "x"}, timeout=0.5)

    assert wait_until(pid_file.exists)
    process_id = pid_file.read_text()
    assert is_running(process_id)
    assert wait_until(lambda: not is_running(process_id), timeout=3)


def test_starting_the_app_does_not_load_the_embedding_model():
    code = "import sys; import src.backend.main; print([name for name in ('fastembed', 'onnxruntime') if name in sys.modules])"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT_DIR, capture_output=True, text=True, check=True)
    assert result.stdout.strip().splitlines()[-1] == "[]"


def test_embedding_worker_exits_after_each_batch(tmp_path, monkeypatch):
    import asyncio

    from src.backend.models.embeddings import client
    from tests.fixtures.fake_embedding_worker import PID_FILE_ENV as EMBEDDING_PID_FILE_ENV

    path = tmp_path / "embedding.pid"
    monkeypatch.setenv(EMBEDDING_PID_FILE_ENV, str(path))
    monkeypatch.setattr(client, "WORKER_MODULE", "tests.fixtures.fake_embedding_worker")

    asyncio.run(client.embed(["job call with Google"]))

    assert wait_until(lambda: not is_running(path.read_text()))
