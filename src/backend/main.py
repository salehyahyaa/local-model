import re
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.backend import db
from src.backend.config import FRONTEND_DIR
from src.backend.integration_routes import router as integration_router
from src.backend.logging_config import setup_logging
from src.backend.models.image_generation.routes import ExposeConnectionEvents
from src.backend.models.image_generation.routes import router as image_generation_router
from src.backend.request_logging import log_requests
from src.backend.routes import router

setup_logging()

HTML_INCLUDE = re.compile(r"<!-- include (\S+) -->")


@asynccontextmanager
async def lifespan(app):
    await db.connect()
    yield
    await db.disconnect()


app = FastAPI(title="Local Chat", lifespan=lifespan)
app.middleware("http")(log_requests)


@app.middleware("http")
async def track_last_accessed(request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        await db.mark_active()
    return await call_next(request)

app.add_middleware(ExposeConnectionEvents)

app.include_router(router)
app.include_router(integration_router)
app.include_router(image_generation_router)


@app.exception_handler(db.DatabaseUnavailableError)
async def database_unavailable(request, error):
    return JSONResponse({"error": "The database is not connected."}, status_code=503)


@app.exception_handler(asyncpg.UndefinedTableError)
async def table_missing(request, error):
    return JSONResponse({"error": "The database is missing a table. Run the migrations in db/migrations."}, status_code=503)


def render_page(path):
    """Fills in each `<!-- include some/file.html -->` so the browser gets one complete page in one request."""
    return HTML_INCLUDE.sub(lambda match: render_page(FRONTEND_DIR / match[1]), path.read_text())


@app.get("/")
async def index():
    return HTMLResponse(render_page(FRONTEND_DIR / "index.html"))


class RevalidatedStaticFiles(StaticFiles):
    """Browsers keep these files but must check for a newer version first, so updates show up on a normal refresh."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/assets", RevalidatedStaticFiles(directory=FRONTEND_DIR), name="static")
