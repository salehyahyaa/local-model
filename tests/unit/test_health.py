"""Health checks and alarms, without a database."""

import asyncio

import pytest

from src.backend.health import alerts, checks, jobs, monitor


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(monitor, "failing", {})
    monkeypatch.setattr(monitor, "last_integration_check", 0.0)
    monkeypatch.setattr(monitor.db, "pool", None)
    monkeypatch.setattr(jobs, "tasks", {})
    monkeypatch.setattr(jobs, "last_errors", {})
    sent = []

    async def record_text(text):
        sent.append(text)

    monkeypatch.setattr(alerts, "send", record_text)
    return sent


def test_a_failure_alerts_once_and_recovery_alerts_once(fresh_state, monkeypatch):
    results = iter([
        [checks.result("disk", "Disk space", "Only 1.0 GB of disk space is left.")],
        [checks.result("disk", "Disk space", "Only 1.0 GB of disk space is left.")],
        [checks.result("disk", "Disk space")],
    ])

    async def local_checks():
        return next(results)

    async def no_integrations():
        return []

    monkeypatch.setattr(checks, "run_local_checks", local_checks)
    monkeypatch.setattr(checks, "check_integrations", no_integrations)

    async def scenario():
        await monitor.run_checks()
        assert [alarm["key"] for alarm in monitor.current_status()["failing"]] == ["disk"]
        await monitor.run_checks()
        await monitor.run_checks()
        assert monitor.current_status()["failing"] == []

    asyncio.run(scenario())
    assert fresh_state == [
        "⚠️ Disk space isn't working: Only 1.0 GB of disk space is left.",
        "✅ Disk space is working again.",
    ]


def test_database_down_is_a_problem():
    [result] = asyncio.run(checks.check_database())
    assert result["key"] == "database"
    assert result["problem"]


def test_a_stopped_or_failing_job_is_a_problem():
    async def scenario():
        async def crash():
            raise RuntimeError("boom")

        stopped = asyncio.create_task(crash())
        await asyncio.sleep(0)
        running = asyncio.create_task(asyncio.sleep(10))
        jobs.watch("task_scan", stopped)
        jobs.watch("call_results", running)
        jobs.failed("call_results", "The last check hit an error.")
        problems = jobs.problems()
        jobs.succeeded("call_results")
        after_success = jobs.problems()
        running.cancel()
        return problems, after_success

    problems, after_success = asyncio.run(scenario())
    assert set(problems) == {"task_scan", "call_results"}
    assert set(after_success) == {"task_scan"}


def test_removed_integrations_stop_alarming(monkeypatch):
    monitor.failing["integration:mcp:9"] = {"name": "Old", "problem": "Couldn't reach it."}
    asyncio.run(monitor.forget_removed_integrations([]))
    assert monitor.failing == {}
