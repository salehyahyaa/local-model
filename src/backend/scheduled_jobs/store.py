"""Saved scheduled tasks."""

from src.backend import db

TASK_COLUMNS = """id, title, instruction, repeat, next_run_at, is_active, last_run_at, last_status,
             last_conversation_id, created_at"""


def to_dict(row):
    def iso(value):
        return value.isoformat() if value else None

    return {
        "id": row["id"],
        "title": row["title"],
        "instruction": row["instruction"],
        "repeat": row["repeat"],
        "nextRunAt": iso(row["next_run_at"]),
        "isActive": row["is_active"],
        "lastRunAt": iso(row["last_run_at"]),
        "lastStatus": row["last_status"],
        "lastConversationId": row["last_conversation_id"],
        "createdAt": iso(row["created_at"]),
    }


async def create(title, instruction, repeat, run_at):
    pool = db.require_pool()
    row = await pool.fetchrow(
        f"""INSERT INTO scheduled_tasks (user_id, title, instruction, repeat, next_run_at)
            VALUES ($1, $2, $3, $4, $5) RETURNING {TASK_COLUMNS}""",
        db.user_id, title, instruction, repeat, run_at,
    )
    return to_dict(row)


async def list_tasks():
    pool = db.require_pool()
    rows = await pool.fetch(
        f"""SELECT {TASK_COLUMNS} FROM scheduled_tasks WHERE user_id = $1
            ORDER BY is_active DESC, next_run_at ASC NULLS LAST, id DESC""",
        db.user_id,
    )
    return [to_dict(row) for row in rows]


async def get(task_id):
    pool = db.require_pool()
    row = await pool.fetchrow(
        f"SELECT {TASK_COLUMNS} FROM scheduled_tasks WHERE id = $1 AND user_id = $2", task_id, db.user_id
    )
    return to_dict(row) if row else None


async def set_active(task_id, is_active, next_run_at):
    pool = db.require_pool()
    row = await pool.fetchrow(
        f"""UPDATE scheduled_tasks SET is_active = $3, next_run_at = $4, updated_at = now()
            WHERE id = $1 AND user_id = $2 RETURNING {TASK_COLUMNS}""",
        task_id, db.user_id, is_active, next_run_at,
    )
    return to_dict(row) if row else None


async def delete(task_id):
    pool = db.require_pool()
    result = await pool.execute("DELETE FROM scheduled_tasks WHERE id = $1 AND user_id = $2", task_id, db.user_id)
    return result != "DELETE 0"


async def due_tasks(now):
    pool = db.require_pool()
    rows = await pool.fetch(
        f"""SELECT {TASK_COLUMNS} FROM scheduled_tasks
            WHERE user_id = $1 AND is_active AND next_run_at <= $2 ORDER BY next_run_at""",
        db.user_id, now,
    )
    return [to_dict(row) for row in rows]


async def finish_run(task_id, ran_at, status, conversation_id, next_run_at):
    """next_run_at None means the task is done and turns off."""
    pool = db.require_pool()
    await pool.execute(
        """UPDATE scheduled_tasks
           SET last_run_at = $3, last_status = $4, last_conversation_id = $5,
               next_run_at = COALESCE($6, next_run_at), is_active = is_active AND $6 IS NOT NULL,
               updated_at = now()
           WHERE id = $1 AND user_id = $2""",
        task_id, db.user_id, ran_at, status, conversation_id, next_run_at,
    )
