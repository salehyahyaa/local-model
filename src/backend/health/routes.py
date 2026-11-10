import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from src.backend import db
from src.backend.health import monitor, store
from src.backend.routes import is_same_origin

logger = logging.getLogger(__name__)


async def require_same_origin(request: Request):
    if not is_same_origin(request):
        logger.warning("Rejected an alarms request from another origin")
        raise HTTPException(status_code=403, detail="Requests from other websites aren't allowed.")


router = APIRouter(prefix="/api", dependencies=[Depends(require_same_origin)])


async def alarms_response():
    """Works without the database too, showing what's failing right now from memory."""
    status = monitor.current_status()
    if db.pool is None:
        active = [
            {"id": None, "key": alarm["key"], "name": alarm["name"], "problem": alarm["problem"],
             "startedAt": None, "resolvedAt": None}
            for alarm in status["failing"]
        ]
        alarms = {"active": active, "resolved": []}
    else:
        alarms = await store.list_alarms()
    return {**alarms, "lastCheckAt": status["lastCheckAt"], "telegramAlerts": status["telegramAlerts"]}


@router.get("/alarms")
async def list_alarms():
    return await alarms_response()


@router.post("/alarms/check")
async def check_now():
    await monitor.run_checks(include_integrations=True)
    return await alarms_response()
