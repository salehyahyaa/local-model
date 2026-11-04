import asyncio
import base64
import binascii
import json
import logging
import os
import re
import sys

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from src.backend.config import IMAGE_DIR, IMAGE_MODEL_PATH, IMAGE_TIMEOUT, ROOT_DIR
from src.backend.models.image_generation import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

MAX_PROMPT_CHARACTERS = 2000
MAX_IMAGES_PER_REQUEST = 20
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 100 * 1024 * 1024
BASE64_SIZE_RATIO = 4 / 3
REQUEST_OVERHEAD_BYTES = 1024 * 1024
EXIT_INVALID_IMAGE = 2
DISCONNECT_CHECK_SECONDS = 1
CONNECTION_RECEIVE = "image_generation.connection_receive"
IMAGE_FILE_NAME = re.compile(r"[0-9a-f]{32}\.png")
WORKER_MODULE = "src.backend.models.image_generation.worker"

# The model needs nearly all of the machine's memory, so only one request is worked on at a time.
generation_lock = asyncio.Lock()


class InvalidImageError(Exception):
    pass


class GenerationFailedError(Exception):
    pass


def decode_image(encoded_image):
    """Decodes a base64 image (with or without a data URL prefix). Returns bytes, or None if invalid or too large."""
    if not isinstance(encoded_image, str):
        return None
    encoded_image = encoded_image.partition("base64,")[2] or encoded_image
    if len(encoded_image) > MAX_IMAGE_BYTES * BASE64_SIZE_RATIO + 4:
        return None
    try:
        return base64.b64decode(encoded_image, validate=True) or None
    except binascii.Error:
        return None


def read_uploads(encoded_images):
    """Returns the decoded images, or an error message for the user."""
    if not isinstance(encoded_images, list):
        return "Invalid images."
    if len(encoded_images) > MAX_IMAGES_PER_REQUEST:
        return f"You can send up to {MAX_IMAGES_PER_REQUEST} images in a message."
    uploads = [decode_image(encoded_image) for encoded_image in encoded_images]
    if None in uploads:
        return "An image is invalid or larger than 20 MB."
    if sum(len(upload) for upload in uploads) > MAX_TOTAL_IMAGE_BYTES:
        return "These images are larger than 100 MB in total."
    return uploads


async def run_worker(job):
    environment = {**os.environ, "PYTORCH_MPS_HIGH_WATERMARK_RATIO": "0.0", "TOKENIZERS_PARALLELISM": "false"}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        WORKER_MODULE,
        cwd=ROOT_DIR,
        env=environment,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    timeout = IMAGE_TIMEOUT * len(job["outputPaths"])
    try:
        _, errors = await asyncio.wait_for(process.communicate(json.dumps(job).encode()), timeout)
    except asyncio.TimeoutError as error:
        process.kill()
        await process.wait()
        raise GenerationFailedError("timed out") from error
    except asyncio.CancelledError:
        process.kill()
        await process.wait()
        raise

    if process.returncode == EXIT_INVALID_IMAGE:
        raise InvalidImageError
    if process.returncode != 0:
        raise GenerationFailedError(errors.decode(errors="replace")[-2000:])


async def run_one_at_a_time(job):
    async with generation_lock:
        logger.info("Making %d image(s) (edit=%s)", len(job["outputPaths"]), bool(job["inputPaths"]))
        await run_worker(job)


class ExposeConnectionEvents:
    """Lets routes see a disconnect, which the app's http middlewares otherwise hide from Request.is_disconnected()."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        scope[CONNECTION_RECEIVE] = receive
        await self.app(scope, receive, send)


async def run_while_connected(request, job):
    """Runs the job, and stops the model if the browser goes away. Returns False if it was stopped."""
    connection = Request(request.scope, request.scope[CONNECTION_RECEIVE])
    generation = asyncio.create_task(run_one_at_a_time(job))
    while not generation.done():
        await asyncio.wait({generation}, timeout=DISCONNECT_CHECK_SECONDS)
        if not generation.done() and await connection.is_disconnected():
            generation.cancel()
            await asyncio.wait({generation})
            logger.info("Stopped image generation because the browser disconnected")
            return False
    generation.result()
    return True


def is_request_too_large(request):
    limit = MAX_TOTAL_IMAGE_BYTES * BASE64_SIZE_RATIO + REQUEST_OVERHEAD_BYTES
    return int(request.headers.get("content-length", 0)) > limit


@router.post("/conversations/{conversation_id}/images", status_code=201)
async def create_image(conversation_id: int, request: Request):
    if is_request_too_large(request):
        return JSONResponse({"error": "These images are larger than 100 MB in total."}, status_code=413)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return JSONResponse({"error": "Invalid image request"}, status_code=422)

    prompt = body.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARACTERS:
        return JSONResponse({"error": "Invalid prompt"}, status_code=422)

    uploads = read_uploads(body.get("images", []))
    if isinstance(uploads, str):
        return JSONResponse({"error": uploads}, status_code=422)

    if not IMAGE_MODEL_PATH.is_file():
        logger.warning("Image model file not found at %s", IMAGE_MODEL_PATH)
        return JSONResponse({"error": "The image model file was not found."}, status_code=503)
    if not await store.conversation_exists(conversation_id):
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    input_files = [store.new_file_name() for _ in uploads]
    output_files = [store.new_file_name() for _ in uploads or [None]]
    new_files = input_files + output_files
    for file_name, upload in zip(input_files, uploads):
        (IMAGE_DIR / file_name).write_bytes(upload)

    job = {
        "modelPath": str(IMAGE_MODEL_PATH),
        "prompt": prompt.strip(),
        "inputPaths": [str(IMAGE_DIR / file_name) for file_name in input_files],
        "outputPaths": [str(IMAGE_DIR / file_name) for file_name in output_files],
    }

    try:
        if not await run_while_connected(request, job):
            store.delete_files(new_files)
            return JSONResponse({"error": "Image generation was stopped."}, status_code=499)
        saved = await store.save_exchange(conversation_id, prompt.strip(), input_files, output_files)
    except InvalidImageError:
        store.delete_files(new_files)
        return JSONResponse({"error": "One of those files isn't an image the model can read."}, status_code=422)
    except GenerationFailedError as error:
        logger.error("Image generation failed: %s", error)
        store.delete_files(new_files)
        return JSONResponse({"error": "The image model failed to make an image."}, status_code=502)
    except BaseException:
        store.delete_files(new_files)
        raise

    if saved is None:
        store.delete_files(new_files)
        return JSONResponse({"error": "Conversation not found"}, status_code=404)
    return saved


@router.get("/images/{file_name}")
async def get_image(file_name: str):
    path = IMAGE_DIR / file_name
    if not IMAGE_FILE_NAME.fullmatch(file_name) or not path.is_file():
        return JSONResponse({"error": "Image not found"}, status_code=404)
    return FileResponse(path, media_type="image/png")
