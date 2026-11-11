import asyncio
import logging
import time

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request

from src.backend import db
from src.backend.agentic_purchases import robinhood, store
from src.backend.routes import is_same_origin

logger = logging.getLogger(__name__)

# Robinhood is asked at most this often; the page refreshes more often than that from the database.
SYNC_SECONDS = 60
SYNC_TIMEOUT = 45

last_sync = {"at": 0.0, "card": None, "problem": None}
sync_lock = asyncio.Lock()


async def require_same_origin(request: Request):
    """Purchase history is private, so only the app's own page may read it."""
    if not is_same_origin(request):
        logger.warning("Rejected an agentic purchases request from another origin")
        raise HTTPException(status_code=403, detail="Requests from other websites aren't allowed.")


router = APIRouter(prefix="/api", dependencies=[Depends(require_same_origin)])


async def sync(server):
    async with sync_lock:
        if time.monotonic() - last_sync["at"] < SYNC_SECONDS:
            return
        try:
            card, transactions = await asyncio.wait_for(robinhood.read_card_activity(server), SYNC_TIMEOUT)
            await store.save_purchases(transactions)
            last_sync.update(card=card, problem=None)
        except (robinhood.Unreachable, asyncio.TimeoutError) as problem:
            logger.warning("Could not sync agentic purchases from Robinhood: %s", type(problem).__name__)
            last_sync["problem"] = str(problem) or "Robinhood didn't answer in time."
        last_sync["at"] = time.monotonic()


@router.get("/agentic-purchases")
async def list_purchases():
    try:
        server = await robinhood.find_server()
        if server is not None:
            await sync(server)
        purchases = await store.list_purchases()
    except (db.DatabaseUnavailableError, asyncpg.PostgresError):
        logger.exception("Could not load agentic purchases")
        raise HTTPException(status_code=503, detail="The database isn't available.") from None
    connection = None
    if server is not None:
        connection = {"name": server["name"], "card": last_sync["card"], "problem": last_sync["problem"]}
    return {"connection": connection, "purchases": purchases}
