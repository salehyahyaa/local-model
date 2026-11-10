"""Each check returns a list of results: {"key", "name", "problem"}. A problem of None means it's working."""

import asyncio
import logging
import shutil

import asyncpg

from src.backend import config, db
from src.backend.appointment_calls import connection as phone_calls
from src.backend.health import jobs
from src.backend.integrations import api_store, mcp_store, service
from src.backend.task_tracker import store as task_store

logger = logging.getLogger(__name__)

DATABASE_CHECK_TIMEOUT = 5
BYTES_PER_GB = 1024**3


def result(key, name, problem=None):
    return {"key": key, "name": name, "problem": problem}


async def check_database():
    if db.pool is None:
        return [result("database", "Database", "The database isn't connected. Chats and settings aren't being saved.")]
    try:
        await asyncio.wait_for(db.pool.fetchval("SELECT 1"), DATABASE_CHECK_TIMEOUT)
    except (OSError, asyncpg.PostgresError, asyncio.TimeoutError) as error:
        logger.warning("Database health check failed: %s", type(error).__name__)
        return [result("database", "Database", "The database isn't answering.")]
    return [result("database", "Database")]


def check_disk():
    free_gb = shutil.disk_usage(config.ROOT_DIR).free / BYTES_PER_GB
    if free_gb < config.MIN_FREE_DISK_GB:
        return [result("disk", "Disk space", f"Only {free_gb:.1f} GB of disk space is left.")]
    return [result("disk", "Disk space")]


def check_jobs():
    found = jobs.problems()
    return [result(f"job:{job}", name, found.get(job)) for job, name in jobs.JOB_NAMES.items() if job in jobs.tasks]


async def check_task_scan():
    """Gmail problems during a scan are saved rather than raised, so they're read from the scan state."""
    if db.pool is None:
        return []
    try:
        state = await task_store.get_scan_state()
    except Exception:
        logger.exception("Could not read the To Do scan state")
        return []
    problem = state["last_error"] if state else None
    return [result("task_scan_gmail", "Email To Do scan", f"Couldn't read Gmail: {problem}" if problem else None)]


async def check_integrations():
    """Contacts every connection that's turned on, so it runs less often than the local checks."""
    if db.pool is None:
        return []
    servers = {server["id"]: server["name"] for server in await mcp_store.list_servers()}
    apis = {integration["id"]: integration["name"] for integration in await api_store.list_integrations()}
    names = {"mcp": servers, "api": apis}
    connections, phone = await asyncio.gather(service.check_health(), phone_calls.check_health())
    results = []
    for status in [*connections, *phone]:
        name = "Phone calls" if status["kind"] == "phone" else names[status["kind"]].get(status["id"], "Integration")
        results.append(result(f"integration:{status['kind']}:{status['id']}", name, status["problem"]))
    return results


async def run_local_checks():
    return [*await check_database(), *check_disk(), *check_jobs(), *await check_task_scan()]
