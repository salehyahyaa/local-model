"""Saves the owner's Telegram chats in the database, in the same conversations and messages as the web app."""

from src.backend import db, store

MAX_TITLE_CHARACTERS = 50


async def connected_pool():
    """The bot can start before the database does, so it keeps trying to connect."""
    if db.pool is None:
        await db.connect()
    return db.require_pool()


async def save_question(sender, telegram_message_id, text):
    """Saves the sender's details and their message, and returns the conversation it went into."""
    pool = await connected_pool()
    async with pool.acquire() as connection, connection.transaction():
        await connection.execute(
            """INSERT INTO telegram_users (telegram_user_id, user_id, first_name, last_name, username)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (telegram_user_id) DO UPDATE SET
                   first_name = EXCLUDED.first_name,
                   last_name = EXCLUDED.last_name,
                   username = EXCLUDED.username,
                   updated_at = now()""",
            sender["id"],
            db.user_id,
            sender.get("first_name"),
            sender.get("last_name"),
            sender.get("username"),
        )
        conversation_id = await find_active_conversation(connection, sender["id"])
        if conversation_id is None:
            conversation_id = await connection.fetchval(
                "INSERT INTO conversations (user_id, title) VALUES ($1, $2) RETURNING id",
                db.user_id,
                f"Telegram: {text[:MAX_TITLE_CHARACTERS]}",
            )
            await connection.execute(
                "INSERT INTO telegram_conversations (conversation_id, telegram_user_id) VALUES ($1, $2)",
                conversation_id,
                sender["id"],
            )
        await connection.execute(
            "INSERT INTO messages (conversation_id, role, content, telegram_message_id) VALUES ($1, 'user', $2, $3)",
            conversation_id,
            text,
            telegram_message_id,
        )
        await connection.execute("UPDATE conversations SET updated_at = now() WHERE id = $1", conversation_id)
    return conversation_id


async def save_reply(conversation_id, text):
    await connected_pool()
    await store.add_message(conversation_id, "assistant", text)


async def end_conversation(telegram_user_id):
    pool = await connected_pool()
    await pool.execute(
        "UPDATE telegram_conversations SET ended_at = now() WHERE telegram_user_id = $1 AND ended_at IS NULL",
        telegram_user_id,
    )


async def load_history(telegram_user_id, limit):
    """The current conversation's answered messages, so a restart doesn't make the model forget them."""
    pool = await connected_pool()
    async with pool.acquire() as connection:
        conversation_id = await find_active_conversation(connection, telegram_user_id)
        if conversation_id is None:
            return []
        rows = await connection.fetch(
            "SELECT role, content FROM messages WHERE conversation_id = $1 ORDER BY id", conversation_id
        )
    return answered_messages([dict(row) for row in rows])[-limit:]


async def find_active_conversation(connection, telegram_user_id):
    return await connection.fetchval(
        """SELECT conversation_id FROM telegram_conversations
           WHERE telegram_user_id = $1 AND ended_at IS NULL
           ORDER BY conversation_id DESC LIMIT 1""",
        telegram_user_id,
    )


def answered_messages(messages):
    """Questions that never got a reply are saved, but the model shouldn't be sent them later."""
    kept = []
    for question, reply in zip(messages, messages[1:]):
        if question["role"] == "user" and reply["role"] == "assistant":
            kept += [question, reply]
    return kept
