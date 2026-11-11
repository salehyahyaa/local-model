"""Runs only the call webhook: venv/bin/python -m src.backend.appointment_calls.webhook_server

The tunnel points here instead of at the main app, so nothing else in the app becomes public.
"""

import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from src.backend import config, db
from src.backend.appointment_calls.webhook import router
from src.backend.logging_config import setup_logging

logger = logging.getLogger(__name__)

NOT_SET_UP = "The webhook secret isn't set. Run: venv/bin/python -m scripts.setup_call_webhook"


@asynccontextmanager
async def lifespan(app):
    await db.connect()
    yield
    await db.disconnect()


# No docs pages: the only public route is the webhook.
app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(router)


def main():
    setup_logging("call_webhook.log")
    if not config.ELEVENLABS_WEBHOOK_SECRET:
        logger.error(NOT_SET_UP)
        sys.exit(1)
    logger.info("Call webhook listening on %s:%s", config.APPOINTMENT_WEBHOOK_HOST, config.APPOINTMENT_WEBHOOK_PORT)
    uvicorn.run(app, host=config.APPOINTMENT_WEBHOOK_HOST, port=config.APPOINTMENT_WEBHOOK_PORT, log_config=None)


if __name__ == "__main__":
    main()
