"""Saved image files and the chat messages they belong to."""

import logging
import uuid

from src.backend import db
from src.backend.config import IMAGE_DIR

logger = logging.getLogger(__name__)

MODEL_ID = "image-generation"


def new_file_name():
    return f"{uuid.uuid4().hex}.png"


def delete_files(file_names):
    for file_name in file_names:
        (IMAGE_DIR / file_name).unlink(missing_ok=True)


async def conversation_exists(conversation_id):
    return await db.require_pool().fetchval(
        "SELECT EXISTS (SELECT 1 FROM conversations WHERE id = $1 AND user_id = $2)", conversation_id, db.user_id
    )


async def files_in_conversation(conversation_id):
    rows = await db.require_pool().fetch(
        """SELECT unnest(m.image_files) AS image_file FROM messages m
           JOIN conversations c ON c.id = m.conversation_id
           WHERE m.conversation_id = $1 AND c.user_id = $2""",
        conversation_id,
        db.user_id,
    )
    return [row["image_file"] for row in rows]


async def insert_message(connection, conversation_id, role, content, image_files):
    await connection.execute(
        "INSERT INTO messages (conversation_id, role, content, model, image_files) VALUES ($1, $2, $3, $4, $5)",
        conversation_id,
        role,
        content,
        MODEL_ID,
        image_files,
    )


async def save_exchange(conversation_id, prompt, input_files, output_files):
    """Saves the prompt and the resulting images as two messages. Returns them, or None if the chat no longer exists."""
    pool = db.require_pool()
    async with pool.acquire() as connection, connection.transaction():
        updated = await connection.execute(
            "UPDATE conversations SET updated_at = now() WHERE id = $1 AND user_id = $2", conversation_id, db.user_id
        )
        if updated == "UPDATE 0":
            return None
        await insert_message(connection, conversation_id, "user", prompt, input_files)
        await insert_message(connection, conversation_id, "assistant", "", output_files)
    return {
        "userMessage": {"role": "user", "content": prompt, "model": MODEL_ID, "imageFiles": input_files},
        "assistantMessage": {"role": "assistant", "content": "", "model": MODEL_ID, "imageFiles": output_files},
    }
