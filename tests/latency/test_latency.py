"""How long single requests take. Budgets are loose enough for shared CI machines; they catch big slowdowns."""

import statistics
import time

import httpx
import pytest

from tests.conftest import TEST_DATABASE_URL

SAMPLES = 50
WARMUP_REQUESTS = 3


def measure_milliseconds(client, path):
    for _ in range(WARMUP_REQUESTS):
        client.get(path)
    timings = []
    for _ in range(SAMPLES):
        started = time.perf_counter()
        response = client.get(path)
        timings.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200, path
    return timings


def p95(timings):
    return statistics.quantiles(timings, n=20)[-1]


@pytest.mark.parametrize(
    ("path", "budget_ms"),
    [
        ("/api/health", 100),
        ("/", 150),
        ("/assets/main.js", 100),
        ("/assets/base.css", 100),
    ],
)
def test_p95_latency_is_within_budget(running_app, path, budget_ms):
    with httpx.Client(base_url=running_app) as client:
        timings = measure_milliseconds(client, path)
    print(f"{path}: median {statistics.median(timings):.1f} ms, p95 {p95(timings):.1f} ms")
    assert p95(timings) < budget_ms


@pytest.mark.skipif(not TEST_DATABASE_URL, reason="Needs TEST_DATABASE_URL")
def test_saved_state_p95_latency_is_within_budget(running_app):
    with httpx.Client(base_url=running_app) as client:
        timings = measure_milliseconds(client, "/api/state")
    print(f"/api/state: median {statistics.median(timings):.1f} ms, p95 {p95(timings):.1f} ms")
    assert p95(timings) < 300
