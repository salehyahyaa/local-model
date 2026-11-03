import json
import logging

import httpx

from src.backend.config import OLLAMA_MODEL, OLLAMA_TIMEOUT, OLLAMA_URL

logger = logging.getLogger(__name__)


class ModelUnavailableError(Exception):
    """No model is connected: Ollama is unreachable, or the model isn't configured/installed."""


async def stream_chat(messages):
    if not OLLAMA_MODEL:
        raise ModelUnavailableError("No model is configured")

    payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": True, "think": False}
    logger.info("Sending %d message(s) to the model", len(messages))
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        try:
            async with client.stream("POST", f"{OLLAMA_URL}/api/chat", json=payload) as response:
                if response.status_code == 404:
                    raise ModelUnavailableError(f"Model '{OLLAMA_MODEL}' is not installed")
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    text_chunk = data.get("message", {}).get("content", "")
                    if text_chunk:
                        yield text_chunk
                    if data.get("done"):
                        logger.info("Model finished (eval_count=%s)", data.get("eval_count"))
                        break
        except httpx.ConnectError as error:
            raise ModelUnavailableError(f"Could not connect to Ollama at {OLLAMA_URL}") from error
