from fastapi import APIRouter

from src.backend.appointment_calls import store

router = APIRouter(prefix="/api")


@router.get("/calls")
async def list_calls():
    return {"calls": await store.list_recent_calls()}
