import asyncio

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from src.backend.autostart import service

router = APIRouter(prefix="/api/autostart")


@router.get("")
async def list_programs():
    return {"programs": await asyncio.to_thread(service.list_programs)}


@router.delete("/{label}")
async def remove_program(label: str, background_tasks: BackgroundTasks):
    if label not in service.PROGRAMS or not await asyncio.to_thread(service.delete_plist, label):
        return JSONResponse({"error": "That program isn't set to start automatically."}, status_code=404)
    # After the response is sent, because stopping the app ends the process answering this request.
    background_tasks.add_task(asyncio.to_thread, service.stop, label)
    return {"removed": label}
