"""Saved conversations, messages and settings for the current user."""

from src.backend import db
from src.backend.attachments import documents

CONVERSATION_FIELDS = {"title": "title", "isPinned": "is_pinned", "isArchived": "is_archived"}
SETTINGS_FIELDS = {
    "theme": "theme",
    "sidebarCollapsed": "sidebar_collapsed",
    "activeConversationId": "active_conversation_id",
    "selectedModel": "selected_model",
}


def conversation_to_dict(row, messages):
    return {
        "id": row["id"],
        "title": row["title"],
        "isPinned": row["is_pinned"],
        "isArchived": row["is_archived"],
        "messages": messages,
    }


async def get_state():
    pool = db.require_pool()
    async with pool.acquire() as connection:
        settings = await connection.fetchrow(
            "SELECT theme, sidebar_collapsed, active_conversation_id, selected_model "
            "FROM user_settings WHERE user_id = $1",
            db.user_id,
        )
        conversation_rows = await connection.fetch(
            "SELECT id, title, is_pinned, is_archived FROM conversations WHERE user_id = $1 ORDER BY id DESC",
            db.user_id,
        )
        message_rows = await connection.fetch(
            """SELECT m.id, m.conversation_id, m.role, m.content, m.model, m.image_files FROM messages m
               JOIN conversations c ON c.id = m.conversation_id
               WHERE c.user_id = $1 ORDER BY m.id""",
            db.user_id,
        )
        documents_by_message = await documents.documents_by_message(connection, db.user_id)

    messages_by_conversation = {}
    for row in message_rows:
        messages_by_conversation.setdefault(row["conversation_id"], []).append(
            {
                "role": row["role"],
                "content": row["content"],
                "model": row["model"],
                "imageFiles": row["image_files"],
                "documents": documents_by_message.get(row["id"], []),
            }
        )
    return {
        "settings": {
            "theme": settings["theme"],
            "sidebarCollapsed": settings["sidebar_collapsed"],
            "activeConversationId": settings["active_conversation_id"],
            "selectedModel": settings["selected_model"],
        },
        "conversations": [
            conversation_to_dict(row, messages_by_conversation.get(row["id"], [])) for row in conversation_rows
        ],
    }


async def create_conversation():
    pool = db.require_pool()
    row = await pool.fetchrow(
        "INSERT INTO conversations (user_id) VALUES ($1) RETURNING id, title, is_pinned, is_archived",
        db.user_id,
    )
    return conversation_to_dict(row, [])


async def update_conversation(conversation_id, changes):
    """changes uses API field names (title, isPinned, isArchived). Returns False if not found."""
    pool = db.require_pool()
    columns = [CONVERSATION_FIELDS[key] for key in changes]
    assignments = ", ".join(f"{column} = ${index + 3}" for index, column in enumerate(columns))
    result = await pool.execute(
        f"UPDATE conversations SET {assignments}, updated_at = now() WHERE id = $1 AND user_id = $2",
        conversation_id,
        db.user_id,
        *changes.values(),
    )
    return result != "UPDATE 0"


async def delete_conversation(conversation_id):
    pool = db.require_pool()
    result = await pool.execute(
        "DELETE FROM conversations WHERE id = $1 AND user_id = $2", conversation_id, db.user_id
    )
    return result != "DELETE 0"


async def clear_conversation(conversation_id):
    """Deletes every message and tool action in a chat but keeps the chat. Returns False if not found."""
    pool = db.require_pool()
    async with pool.acquire() as connection, connection.transaction():
        owns_conversation = await connection.fetchval(
            "SELECT EXISTS (SELECT 1 FROM conversations WHERE id = $1 AND user_id = $2)", conversation_id, db.user_id
        )
        if not owns_conversation:
            return False
        await connection.execute("DELETE FROM messages WHERE conversation_id = $1", conversation_id)
        await connection.execute("DELETE FROM tool_activity WHERE conversation_id = $1", conversation_id)
        await connection.execute("UPDATE conversations SET updated_at = now() WHERE id = $1", conversation_id)
        return True


async def add_message(conversation_id, role, content, model=None):
    pool = db.require_pool()
    async with pool.acquire() as connection, connection.transaction():
        message_id = await connection.fetchval(
            """INSERT INTO messages (conversation_id, role, content, model)
               SELECT id, $3, $4, $5 FROM conversations WHERE id = $1 AND user_id = $2
               RETURNING id""",
            conversation_id,
            db.user_id,
            role,
            content,
            model,
        )
        if message_id is not None:
            await connection.execute("UPDATE conversations SET updated_at = now() WHERE id = $1", conversation_id)
        return message_id


async def image_files_of_last_message(conversation_id):
    pool = db.require_pool()
    image_files = await pool.fetchval(
        """SELECT m.image_files FROM messages m JOIN conversations c ON c.id = m.conversation_id
           WHERE m.conversation_id = $1 AND c.user_id = $2 ORDER BY m.id DESC LIMIT 1""",
        conversation_id,
        db.user_id,
    )
    return list(image_files or [])


async def delete_last_message(conversation_id):
    pool = db.require_pool()
    result = await pool.execute(
        """DELETE FROM messages WHERE id = (
               SELECT m.id FROM messages m JOIN conversations c ON c.id = m.conversation_id
               WHERE m.conversation_id = $1 AND c.user_id = $2
               ORDER BY m.id DESC LIMIT 1)""",
        conversation_id,
        db.user_id,
    )
    return result != "DELETE 0"


async def update_settings(changes):
    """changes uses API field names. Returns False if activeConversationId isn't one of the user's chats."""
    pool = db.require_pool()
    async with pool.acquire() as connection, connection.transaction():
        active_id = changes.get("activeConversationId")
        if active_id is not None:
            owns_conversation = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM conversations WHERE id = $1 AND user_id = $2)", active_id, db.user_id
            )
            if not owns_conversation:
                return False
        columns = [SETTINGS_FIELDS[key] for key in changes]
        assignments = ", ".join(f"{column} = ${index + 2}" for index, column in enumerate(columns))
        await connection.execute(
            f"UPDATE user_settings SET {assignments}, updated_at = now() WHERE user_id = $1",
            db.user_id,
            *changes.values(),
        )
        return True
