import asyncio
import json
import logging
from urllib.parse import urlencode

from fastapi import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from src.backend.config import DEEPGRAM_API_KEY, DEEPGRAM_MODEL, DEEPGRAM_TIMEOUT

logger = logging.getLogger(__name__)

DEEPGRAM_STREAM_URL = "wss://api.deepgram.com/v1/listen"
CLOSE_STREAM_MESSAGE = json.dumps({"type": "CloseStream"})
FINISH_MESSAGE = "finish"
MAX_AUDIO_BYTES = 40 * 1024 * 1024  # Fits the 20-minute voice limit in speechDetector.js (16 kHz, 16-bit mono).


def stream_url():
    params = {
        "model": DEEPGRAM_MODEL,
        "encoding": "linear16",
        "sample_rate": 16000,
        "channels": 1,
        "interim_results": "true",
        "smart_format": "true",
    }
    return f"{DEEPGRAM_STREAM_URL}?{urlencode(params)}"


async def send_to_browser(client: WebSocket, message):
    try:
        await client.send_json(message)
    except (WebSocketDisconnect, RuntimeError):
        logger.debug("Browser left before a transcript could be sent")


async def forward_audio(client: WebSocket, deepgram):
    """Passes the browser's audio to Deepgram until it says it's finished, or goes away."""
    sent_bytes = 0
    finished = False
    try:
        while True:
            message = await client.receive()
            if message["type"] == "websocket.disconnect":
                await deepgram.close()
                return
            if finished:
                continue

            audio = message.get("bytes")
            if audio and sent_bytes + len(audio) <= MAX_AUDIO_BYTES:
                sent_bytes += len(audio)
                await deepgram.send(audio)
            elif audio or message.get("text") == FINISH_MESSAGE:
                finished = True
                await deepgram.send(CLOSE_STREAM_MESSAGE)
    except ConnectionClosed:
        logger.debug("Deepgram closed the stream while audio was being forwarded")


async def relay_transcripts(deepgram, client: WebSocket):
    """Sends the browser everything heard so far as Deepgram refines it. Returns the final text."""
    final_parts = []
    async for raw_message in deepgram:
        message = json.loads(raw_message)
        if message.get("type") != "Results":
            continue

        transcript = message["channel"]["alternatives"][0]["transcript"].strip()
        is_final = message.get("is_final", False)
        if is_final and transcript:
            final_parts.append(transcript)
        if transcript:
            parts = final_parts if is_final else [*final_parts, transcript]
            await send_to_browser(client, {"text": " ".join(parts)})
    return " ".join(final_parts)


async def stream_transcription(client: WebSocket):
    """Streams one utterance: audio frames in, growing text out, then {"done": true, "text": ...}."""
    if not DEEPGRAM_API_KEY:
        logger.warning("Speech-to-text unavailable: DEEPGRAM_API_KEY is not set")
        await send_to_browser(client, {"error": "Speech-to-text is not configured."})
        return

    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
    try:
        async with connect(stream_url(), additional_headers=headers, open_timeout=DEEPGRAM_TIMEOUT) as deepgram:
            forwarder = asyncio.create_task(forward_audio(client, deepgram))
            try:
                text = await relay_transcripts(deepgram, client)
            finally:
                forwarder.cancel()
                await asyncio.gather(forwarder, return_exceptions=True)
    except (OSError, TimeoutError, WebSocketException, KeyError, IndexError, ValueError):
        logger.exception("Streaming transcription failed")
        await send_to_browser(client, {"error": "The transcription request failed."})
        return

    await send_to_browser(client, {"done": True, "text": text})
