import logging

import httpx

from src.backend.config import DEEPGRAM_API_KEY, DEEPGRAM_MODEL, DEEPGRAM_TIMEOUT

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"


class TranscriptionUnavailableError(Exception):
    """Speech-to-text isn't configured (no Deepgram API key)."""


async def transcribe(audio, content_type):
    if not DEEPGRAM_API_KEY:
        raise TranscriptionUnavailableError("DEEPGRAM_API_KEY is not set")

    params = {"model": DEEPGRAM_MODEL, "smart_format": "true"}
    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}", "Content-Type": content_type}
    logger.info("Sending %d bytes of audio to Deepgram", len(audio))
    async with httpx.AsyncClient(timeout=DEEPGRAM_TIMEOUT) as client:
        response = await client.post(DEEPGRAM_URL, params=params, headers=headers, content=audio)
        response.raise_for_status()

    alternatives = response.json()["results"]["channels"][0]["alternatives"]
    return alternatives[0]["transcript"].strip() if alternatives else ""
