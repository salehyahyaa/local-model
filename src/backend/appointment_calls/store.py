import json
from src.backend import db

RECENT_CALLS = 20


async def conversation_exists(conversation_id):
    pool = db.require_pool()
    return await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM conversations WHERE id = $1 AND user_id = $2)", conversation_id, db.user_id
    )


async def reserve_call(call, conversation_id):
    """Saves the call before dialing, so a crash can't leave a real call the app doesn't know about."""
    pool = db.require_pool()
    return await pool.fetchval(
        """INSERT INTO appointment_calls
               (user_id, conversation_id, contact_name, phone_number, reason, allowed_slots, timezone, deadline)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
           RETURNING id""",
        db.user_id,
        conversation_id,
        call["contact_name"],
        call["phone_number"],
        call["reason"],
        json.dumps(call["allowed_slots"]),
        call["timezone"],
        call["deadline"],
    )


async def save_call_ids(call_id, conversation_id, call_sid):
    pool = db.require_pool()
    await pool.execute(
        """UPDATE appointment_calls
           SET elevenlabs_conversation_id = $3, twilio_call_sid = $4, updated_at = now()
           WHERE id = $1 AND user_id = $2""",
        call_id,
        db.user_id,
        conversation_id,
        call_sid,
    )


def row_to_call(row):
    return {**dict(row), "allowed_slots": json.loads(row["allowed_slots"])}


async def list_active_calls():
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT *, EXTRACT(EPOCH FROM now() - created_at) AS age_seconds
           FROM appointment_calls WHERE user_id = $1 AND status = 'calling'""",
        db.user_id,
    )
    return [row_to_call(row) for row in rows]


async def finish_call(call_id, status, result_message, booked_time=None, post_to_chat=True):
    """Saves the outcome and posts it to the chat together. Returns False if it was already finished."""
    pool = db.require_pool()
    async with pool.acquire() as connection, connection.transaction():
        row = await connection.fetchrow(
            """UPDATE appointment_calls
               SET status = $3, result_message = $4, booked_time = $5, updated_at = now()
               WHERE id = $1 AND user_id = $2 AND status = 'calling'
               RETURNING conversation_id""",
            call_id,
            db.user_id,
            status,
            result_message,
            booked_time,
        )
        if row is None:
            return False
        if post_to_chat and row["conversation_id"] is not None:
            await connection.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES ($1, 'assistant', $2)",
                row["conversation_id"],
                result_message,
            )
            await connection.execute(
                "UPDATE conversations SET updated_at = now() WHERE id = $1", row["conversation_id"]
            )
        return True


async def list_recent_calls():
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT id, conversation_id, contact_name, status, result_message
           FROM appointment_calls WHERE user_id = $1 ORDER BY id DESC LIMIT $2""",
        db.user_id,
        RECENT_CALLS,
    )
    return [
        {
            "id": row["id"],
            "conversationId": row["conversation_id"],
            "contactName": row["contact_name"],
            "status": row["status"],
            "resultMessage": row["result_message"],
        }
        for row in rows
    ]


async def get_connection():
    pool = db.require_pool()
    return await pool.fetchrow("SELECT * FROM phone_call_connections WHERE user_id = $1", db.user_id)


async def create_connection(connection):
    pool = db.require_pool()
    return await pool.fetchrow(
        """INSERT INTO phone_call_connections (user_id, owner_name, agent_id, phone_number_id)
           VALUES ($1, $2, $3, $4) RETURNING *""",
        db.user_id,
        connection["owner_name"],
        connection["agent_id"],
        connection["phone_number_id"],
    )


async def set_enabled(connection_id, enabled):
    pool = db.require_pool()
    result = await pool.execute(
        "UPDATE phone_call_connections SET enabled = $3, updated_at = now() WHERE id = $1 AND user_id = $2",
        connection_id,
        db.user_id,
        enabled,
    )
    return result != "UPDATE 0"


async def delete_connection(connection_id):
    pool = db.require_pool()
    result = await pool.execute(
        "DELETE FROM phone_call_connections WHERE id = $1 AND user_id = $2", connection_id, db.user_id
    )
    return result != "DELETE 0"
