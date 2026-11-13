"""Saves every error the app runs into, so the model can learn from its own mistakes later.

Saving never stops a reply: a database problem is logged by type only and the chat carries on.
"""

import logging

from src.backend import db

logger = logging.getLogger(__name__)

CHAT = "chat"
TELEGRAM = "telegram"

MAX_SAVED_MESSAGE = 4000


async def save(source, kind, message, attempted=None, conversation_id=None):
    """A conversation id is only kept if it is one of the owner's own chats."""
    pool = db.require_pool()
    await pool.execute(
        """INSERT INTO error_log (user_id, conversation_id, source, kind, message, attempted)
           VALUES ($1, (SELECT id FROM conversations WHERE id = $2 AND user_id = $1), $3, $4, $5, $6)""",
        db.user_id,
        conversation_id,
        source,
        kind,
        (message or kind)[:MAX_SAVED_MESSAGE],
        attempted,
    )


async def record(source, kind, message, attempted=None, conversation_id=None):
    logger.warning("%s error while %s: %s", source, attempted or "working", kind)
    try:
        await save(source, kind, message, attempted, conversation_id)
    except Exception as error:
        logger.error("Could not save an error: %s", type(error).__name__)
