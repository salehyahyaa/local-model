import os
import subprocess
import sys
import tempfile

import pytest

# Tests never read or write the real OS keychain; secrets come from environment variables only.
os.environ["USE_KEYCHAIN"] = "0"
# Tests never write into the real logs/app.log, which the owner reads to evaluate the model.
os.environ["LOG_DIR"] = tempfile.mkdtemp(prefix="local-model-test-logs-")

from tests.helpers import ROOT_DIR, find_free_port, reset_test_database, wait_for_port  # noqa: E402

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")
UNREACHABLE_PORT = "1"


@pytest.fixture(scope="module")
def running_app(tmp_path_factory):
    """The real app in its own server process. Only ever uses the test database, or no database at all."""
    working_dir = tmp_path_factory.mktemp("running_app")
    environment = {
        **os.environ,
        "ENV_FILE": str(working_dir / ".env"),
        "LOG_DIR": str(working_dir / "logs"),
        "IMAGE_DIR": str(working_dir / "images"),
        "DATABASE_URL": TEST_DATABASE_URL,
    }
    if TEST_DATABASE_URL:
        reset_test_database(TEST_DATABASE_URL)
    else:
        environment["DATABASE_PORT"] = UNREACHABLE_PORT

    port = find_free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "src.backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT_DIR,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for_port(port, timeout=30)
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture(autouse=True)
def no_real_phone_call_settings(monkeypatch):
    """Phone calls stay off in tests unless a test turns them on, whatever the owner's .env says."""
    from src.backend import config

    for name in ("ELEVENLABS_API_KEY", "ELEVENLABS_AGENT_ID", "ELEVENLABS_PHONE_NUMBER_ID", "CALL_OWNER_NAME"):
        monkeypatch.setattr(config, name, "")
