import asyncio
import logging
import re
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.backend import db
from src.backend.analytics.routes import router as analytics_router
from src.backend.appointment_calls import poller as appointment_call_poller
from src.backend.appointment_calls.routes import router as appointment_calls_router
from src.backend.attachments import documents
from src.backend.attachments.routes import router as attachments_router
from src.backend.autostart.routes import router as autostart_router
from src.backend.chat_memory import embeddings as search_embeddings
from src.backend.chat.routes import router as chat_router
from src.backend.config import FRONTEND_DIR
from src.backend.health import jobs as health_jobs
from src.backend.health import monitor as health_monitor
from src.backend.health.routes import router as health_router
from src.backend.integration_routes import router as integration_router
from src.backend.logging_config import setup_logging
from src.backend.models.image_generation.routes import ExposeConnectionEvents
from src.backend.models.image_generation.routes import router as image_generation_router
from src.backend.models.openai_temporary import model as openai_temporary
from src.backend.request_logging import log_requests
from src.backend.routes import router
from src.backend.settings_panel.routes import router as settings_panel_router
from src.backend.task_tracker import poller as task_poller
from src.backend.task_tracker.routes import router as task_tracker_router

setup_logging()

logger = logging.getLogger(__name__)

HTML_INCLUDE = re.compile(r"<!-- include (\S+) -->")


@asynccontextmanager
async def lifespan(app):
    openai_temporary.connect()
    await db.connect()
    if db.pool is not None:
        try:
            await documents.delete_orphaned_files()
        except Exception:
            logging.getLogger(__name__).exception("Could not clean up orphaned document files")
    call_results = asyncio.create_task(appointment_call_poller.run()) if db.pool is not None else None
    task_scans = asyncio.create_task(task_poller.run()) if db.pool is not None else None
    if call_results is not None:
        health_jobs.watch("call_results", call_results)
    if task_scans is not None:
        health_jobs.watch("task_scan", task_scans)
    # Only starts the embedding model when there are new messages to embed.
    embedding_updates = asyncio.create_task(search_embeddings.run()) if db.pool is not None else None
    if embedding_updates is not None:
        health_jobs.watch(search_embeddings.JOB, embedding_updates)
    health_checks = asyncio.create_task(health_monitor.run())
    yield
    health_checks.cancel()
    if embedding_updates is not None:
        embedding_updates.cancel()
    if call_results is not None:
        call_results.cancel()
    if task_scans is not None:
        task_scans.cancel()
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
app.include_router(chat_router)
app.include_router(settings_panel_router)
app.include_router(attachments_router)
app.include_router(autostart_router)
app.include_router(appointment_calls_router)
app.include_router(task_tracker_router)
app.include_router(health_router)
app.include_router(integration_router)
app.include_router(image_generation_router)
app.include_router(analytics_router)


@app.exception_handler(db.DatabaseUnavailableError)
async def database_unavailable(request, error):
    return JSONResponse({"error": "The database is not connected."}, status_code=503)


@app.exception_handler(asyncpg.UndefinedTableError)
async def table_missing(request, error):
    logger.error("Database table missing on %s %s: %s", request.method, request.url.path, error)
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
