"""Client for a local Ollama model."""

import json
import logging
from collections.abc import AsyncIterator

import httpx

from src.backend.config import OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL

logger = logging.getLogger(__name__)


async def stream_chat(messages: list[dict]) -> AsyncIterator[str]:
    """Stream response text chunks from Ollama's /api/chat endpoint."""
    payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": True, "think": False}
    logger.info("Sending %d message(s) to model %s", len(messages), OLLAMA_MODEL)
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk
                if data.get("done"):
                    logger.info("Model finished (eval_count=%s)", data.get("eval_count"))
                    break
