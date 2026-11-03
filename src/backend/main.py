from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.backend.config import FRONTEND_DIR
from src.backend.logging_config import setup_logging
from src.backend.request_logging import log_requests
from src.backend.routes import router

setup_logging()

app = FastAPI(title="Local Chat")
app.middleware("http")(log_requests)
app.include_router(router)


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
