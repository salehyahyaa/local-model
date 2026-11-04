import logging
import time

logger = logging.getLogger(__name__)


def level_for_status(status_code):
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    return logging.INFO


async def log_requests(request, call_next):
    start_time = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        # Uvicorn only prints these to the console, so without this a crash would be missing from app.log.
        logger.exception("%s %s crashed", request.method, request.url.path)
        raise
    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.log(
        level_for_status(response.status_code),
        "%s %s -> %d (%.1f ms)",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
