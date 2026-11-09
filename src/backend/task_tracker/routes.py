import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from src.backend.chat import model_slot
from src.backend.routes import is_same_origin
from src.backend.task_tracker import scanner, store

logger = logging.getLogger(__name__)


async def require_same_origin(request: Request):
    """These routes show email subjects and change tasks, so only the app's own page may use them."""
    if not is_same_origin(request):
        logger.warning("Rejected a task request from another origin")
        raise HTTPException(status_code=403, detail="Requests from other websites aren't allowed.")


router = APIRouter(prefix="/api", dependencies=[Depends(require_same_origin)])


def is_catching_up(state):
    if state is None or state["scanned_through"] is None:
        return True
    return state["scanned_through"] < datetime.now(timezone.utc).date() - timedelta(days=1)


async def tasks_response():
    state = await store.get_scan_state()
    return {
        **await store.list_tasks(),
        "gmailConnected": await scanner.is_gmail_connected(),
        "modelConnected": model_slot.connected_model is not None,
        "scanning": scanner.is_scanning(),
        "catchingUp": is_catching_up(state),
        "lastScanAt": state["last_scan_at"].isoformat() if state and state["last_scan_at"] else None,
        "waitingCount": state["waiting_count"] if state else 0,
        "lastError": state["last_error"] if state else None,
    }


@router.get("/tasks")
async def list_tasks():
    return await tasks_response()


async def change_task(task_id, change):
    if not await store.task_exists(task_id):
        return JSONResponse({"error": "That task no longer exists."}, status_code=404)
    await change(task_id)
    return await tasks_response()


@router.post("/tasks/{task_id}/complete")
async def complete_task(task_id: int):
    return await change_task(task_id, store.mark_done)


@router.post("/tasks/{task_id}/reopen")
async def reopen_task(task_id: int):
    return await change_task(task_id, store.reopen)
