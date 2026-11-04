import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.backend.main import app
from src.backend.models.image_generation import routes as image_routes
from src.backend.request_logging import log_requests

REQUEST_LOGGER = "src.backend.request_logging"


def make_client():
    test_app = FastAPI()
    test_app.middleware("http")(log_requests)

    @test_app.get("/fine")
    async def fine():
        return {}

    @test_app.get("/rejected")
    async def rejected():
        return JSONResponse({}, status_code=422)

    @test_app.get("/broken")
    async def broken():
        return JSONResponse({}, status_code=503)

    @test_app.get("/crash")
    async def crash():
        raise RuntimeError("boom")

    return TestClient(test_app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    ("path", "level"),
    [("/fine", logging.INFO), ("/rejected", logging.WARNING), ("/broken", logging.ERROR)],
)
def test_request_log_level_follows_status(caplog, path, level):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        make_client().get(path)
    assert [record.levelno for record in caplog.records if record.name == REQUEST_LOGGER] == [level]


def test_crash_is_logged_with_its_traceback(caplog):
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER):
        assert make_client().get("/crash").status_code == 500
    record = next(record for record in caplog.records if "/crash crashed" in record.getMessage())
    assert record.levelno == logging.ERROR
    assert "boom" in str(record.exc_info[1])


def test_browser_error_is_logged_on_one_line(caplog):
    with caplog.at_level(logging.ERROR, logger="src.backend.routes"):
        response = TestClient(app).post("/api/client-errors", json={"message": "bad\nfake entry", "stack": "at x"})
    assert response.status_code == 204
    logged = next(record.getMessage() for record in caplog.records if "Browser error" in record.getMessage())
    assert "bad\\nfake entry" in logged
    assert "\n" not in logged


def test_browser_error_report_must_be_an_object():
    assert TestClient(app).post("/api/client-errors", json=["nope"]).status_code == 422


def test_failed_worker_reports_its_exit_code(tmp_path, monkeypatch):
    (tmp_path / "silent_crash_worker.py").write_text("import sys; sys.exit(9)")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    monkeypatch.setattr(image_routes, "WORKER_MODULE", "silent_crash_worker")
    job = {"modelPath": "unused", "prompt": "x", "inputPaths": [], "outputPaths": ["unused"]}
    with pytest.raises(image_routes.GenerationFailedError, match="exit code 9"):
        asyncio.run(image_routes.run_worker(job))
