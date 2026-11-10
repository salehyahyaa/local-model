"""Checks Gmail for unfinished work every few minutes while the app is running.

The last scanned date is in the database, so scanning catches up after the Mac sleeps or the app restarts.
"""

import asyncio
import logging

from src.backend import config
from src.backend.health import jobs
from src.backend.task_tracker import scanner

logger = logging.getLogger(__name__)


async def run():
    while True:
        try:
            await scanner.scan()
            jobs.succeeded("task_scan")
        except Exception:
            # One bad scan must not stop every later one.
            logger.exception("Could not scan for unfinished tasks")
            jobs.failed("task_scan", "The last scan hit an error. See logs/app.log.")
        await asyncio.sleep(config.TASK_SCAN_SECONDS)
