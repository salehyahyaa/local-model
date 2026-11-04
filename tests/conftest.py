import os
import subprocess
import sys

import pytest

# Tests never read or write the real OS keychain; secrets come from environment variables only.
os.environ["USE_KEYCHAIN"] = "0"

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
