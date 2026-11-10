import logging

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from src.backend import db
from src.backend.analytics import queries
from src.backend.config import FRONTEND_DIR
from src.backend.routes import is_same_origin

logger = logging.getLogger(__name__)

RANGES = (7, 30, 90, 365)
PAGE = FRONTEND_DIR / "analytics" / "analytics.html"

router = APIRouter()


@router.get("/analytics")
async def analytics_page():
    return HTMLResponse(PAGE.read_text())


@router.get("/api/analytics")
async def analytics(request: Request, days: int = Query(30)):
    # Shows chat activity and tool use, so only the app's own pages may read it.
    if not is_same_origin(request):
        logger.warning("Rejected an analytics request from another origin")
        raise HTTPException(status_code=403, detail="Requests from other websites aren't allowed.")
    if days not in RANGES:
        raise HTTPException(status_code=422, detail=f"days must be one of {', '.join(map(str, RANGES))}")
    db.require_pool()
    return await queries.collect(days)
