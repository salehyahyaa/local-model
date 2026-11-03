"""FastAPI app: serves the chat API and the static frontend."""

import logging
import time
from typing import Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.backend import llm
from src.backend.config import FRONTEND_DIR, OLLAMA_MODEL
from src.backend.logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Local Model Chat")


class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - start) * 1000
    logger.info("%s %s -> %d (%.1f ms)", request.method, request.url.path, response.status_code, ms)
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok", "model": OLLAMA_MODEL}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    messages = [m.model_dump() for m in req.messages]

    async def generate():
        try:
            async for chunk in llm.stream_chat(messages):
                yield chunk
        except httpx.HTTPError as exc:
            logger.exception("Model request failed")
            yield f"\n[Error: could not reach the model ({exc.__class__.__name__}). Is Ollama running?]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
