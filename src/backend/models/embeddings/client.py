"""The app's side of the embedding model: starts a worker for each batch and reads the numbers back.

The model is never loaded in the app's own process, so it only uses memory while a batch is being embedded.
"""

import asyncio
import json
import os
import sys

from src.backend.config import EMBEDDING_CACHE_DIR, ROOT_DIR
from src.backend.models.embeddings import DIMENSIONS

WORKER_MODULE = "src.backend.models.embeddings.worker"
# The first run downloads the model (about 70 MB), so it gets far longer than later runs need.
TIMEOUT_SECONDS = 600


class EmbeddingError(Exception):
    pass


def read_vectors(output, count):
    try:
        vectors = json.loads(output)["vectors"]
    except (ValueError, KeyError, TypeError) as error:
        raise EmbeddingError("the worker's answer couldn't be read") from error
    if not isinstance(vectors, list) or len(vectors) != count:
        raise EmbeddingError("the worker returned the wrong number of results")
    if any(not isinstance(vector, list) or len(vector) != DIMENSIONS for vector in vectors):
        raise EmbeddingError("the worker returned numbers of the wrong size")
    return vectors


async def embed(texts):
    """Returns one list of DIMENSIONS numbers per text."""
    if not texts:
        return []
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        WORKER_MODULE,
        cwd=ROOT_DIR,
        env={**os.environ, "TOKENIZERS_PARALLELISM": "false"},
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    job = {"texts": list(texts), "cacheDir": str(EMBEDDING_CACHE_DIR)}
    try:
        output, errors = await asyncio.wait_for(process.communicate(json.dumps(job).encode()), TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, asyncio.CancelledError) as error:
        process.kill()
        await process.wait()
        if isinstance(error, asyncio.CancelledError):
            raise
        raise EmbeddingError("the model took too long") from error
    if process.returncode != 0:
        raise EmbeddingError(f"worker exit code {process.returncode}: {errors.decode(errors='replace')[-500:]}")
    return read_vectors(output, len(texts))
