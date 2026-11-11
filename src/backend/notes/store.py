from src.backend import db


def row_to_note(row):
    return {
        "id": row["id"],
        "text": row["text"],
        "color": row["color"],
        "updatedAt": row["updated_at"].isoformat(),
    }


async def list_notes():
    pool = db.require_pool()
    rows = await pool.fetch(
        "SELECT id, text, color, updated_at FROM notes WHERE user_id = $1 ORDER BY id DESC",
        db.user_id,
    )
    return [row_to_note(row) for row in rows]


async def create_note(color, text=""):
    pool = db.require_pool()
    row = await pool.fetchrow(
        "INSERT INTO notes (user_id, color, text) VALUES ($1, $2, $3) RETURNING id, text, color, updated_at",
        db.user_id,
        color,
        text,
    )
    return row_to_note(row)


async def update_note(note_id, changes):
    """Returns False when the note doesn't exist."""
    pool = db.require_pool()
    result = await pool.execute(
        """UPDATE notes SET text = COALESCE($3, text), color = COALESCE($4, color), updated_at = now()
           WHERE id = $1 AND user_id = $2""",
        note_id,
        db.user_id,
        changes.get("text"),
        changes.get("color"),
    )
    return result != "UPDATE 0"


async def delete_note(note_id):
    pool = db.require_pool()
    result = await pool.execute(
        "DELETE FROM notes WHERE id = $1 AND user_id = $2", note_id, db.user_id
    )
    return result != "DELETE 0"
