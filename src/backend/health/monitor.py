"""Runs the health checks on a timer and turns failures into alarms.

Alarms are kept in memory as well as the database, so a database outage still gets logged and texted.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from src.backend import config, db
from src.backend.health import alerts, checks, store

logger = logging.getLogger(__name__)

failing = {}  # check_key -> {"name", "problem"}
integration_results = []
last_integration_check = 0.0
last_check_at = None
check_lock = asyncio.Lock()


async def load_open_alarms():
    """After a restart, alarms that were already open aren't announced a second time."""
    if db.pool is None:
        return
    try:
        for key, problem in (await store.active_problems()).items():
            failing.setdefault(key, {"name": key, "problem": problem})
    except Exception:
        logger.exception("Could not load open alarms")


async def save(change, *args):
    if db.pool is None:
        return
    try:
        await change(*args)
    except Exception:
        logger.exception("Could not save an alarm change")


async def apply_result(result):
    key, name, problem = result["key"], result["name"], result["problem"]
    previous = failing.get(key)
    if problem is None:
        if previous is not None:
            del failing[key]
            logger.info("Health check %s is working again", key)
            await save(store.resolve_alarm, key)
            await alerts.send(alerts.recovery_text(name))
        return
    failing[key] = {"name": name, "problem": problem}
    if previous is None or previous["problem"] != problem:
        await save(store.raise_alarm, key, name, problem)
    if previous is None:
        logger.error("Health check %s failed: %s", key, problem)
        await alerts.send(alerts.failure_text(name, problem))


async def forget_removed_integrations(results):
    keys = {result["key"] for result in results}
    for key in [key for key in failing if key.startswith("integration:") and key not in keys]:
        del failing[key]
    await save(store.resolve_missing, keys)


async def run_checks(include_integrations=False):
    """Runs every check once. Integrations are contacted only when asked, or every few minutes."""
    global integration_results, last_integration_check, last_check_at
    async with check_lock:
        results = await checks.run_local_checks()
        due = time.monotonic() - last_integration_check >= config.INTEGRATION_HEALTH_CHECK_SECONDS
        if include_integrations or due:
            try:
                integration_results = await checks.check_integrations()
                await forget_removed_integrations(integration_results)
            except Exception:
                logger.exception("Could not check integrations")
            last_integration_check = time.monotonic()
            results.extend(integration_results)
        for result in results:
            await apply_result(result)
        last_check_at = datetime.now(timezone.utc)


async def run():
    await load_open_alarms()
    while True:
        try:
            await run_checks()
        except Exception:
            # A broken check must not stop every later one.
            logger.exception("Health checks failed to run")
        await asyncio.sleep(config.HEALTH_CHECK_SECONDS)


def current_status():
    return {
        "failing": [{"key": key, **value} for key, value in failing.items()],
        "lastCheckAt": last_check_at.isoformat() if last_check_at else None,
        "telegramAlerts": alerts.is_set_up(),
    }
