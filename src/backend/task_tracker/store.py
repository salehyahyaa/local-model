from urllib.parse import quote

from src.backend import db

RECENTLY_CLOSED_LIMIT = 20
RECENTLY_CLOSED_DAYS = 30


def gmail_url(message_id):
    """Opens the email by its Message-ID. Emails without one can't be linked."""
    if not message_id or message_id.startswith("uid:"):
        return None
    return "https://mail.google.com/mail/u/0/#search/" + quote(f"rfc822msgid:{message_id.strip('<>')}", safe="")


def row_to_task(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "company": row["company"],
        "emailDate": row["request_date"].isoformat(),
        "deadline": row["deadline"].isoformat() if row["deadline"] else None,
        "status": row["status"],
        "closedBy": row["closed_by"],
        "closedAt": row["closed_at"].isoformat() if row["closed_at"] else None,
        "gmailUrl": gmail_url(row["request_message_id"]),
    }


async def fetch_recently_closed():
    pool = db.require_pool()
    return await pool.fetch(
        """SELECT * FROM tracked_tasks
           WHERE user_id = $1 AND status = 'completed' AND closed_at > now() - make_interval(days => $2)
           ORDER BY closed_at DESC LIMIT $3""",
        db.user_id,
        RECENTLY_CLOSED_DAYS,
        RECENTLY_CLOSED_LIMIT,
    )


async def fetch_open():
    pool = db.require_pool()
    return await pool.fetch(
        """SELECT * FROM tracked_tasks WHERE user_id = $1 AND status = 'open'
           ORDER BY deadline ASC NULLS LAST, request_date ASC""",
        db.user_id,
    )


async def list_tasks():
    return {
        "open": [row_to_task(row) for row in await fetch_open()],
        "completed": [row_to_task(row) for row in await fetch_recently_closed()],
    }


async def tasks_for_model():
    """Closed tasks are included so a reminder about something marked done doesn't list it again."""
    rows = [*await fetch_open(), *await fetch_recently_closed()]
    return [{"id": row["id"], "title": row["title"], "company": row["company"], "status": row["status"]} for row in rows]


async def task_exists(task_id):
    pool = db.require_pool()
    return await pool.fetchval(
        "SELECT EXISTS (SELECT 1 FROM tracked_tasks WHERE id = $1 AND user_id = $2)", task_id, db.user_id
    )


async def mark_done(task_id):
    pool = db.require_pool()
    await pool.execute(
        """UPDATE tracked_tasks
           SET status = 'completed', closed_by = 'manual', closed_at = now(), updated_at = now()
           WHERE id = $1 AND user_id = $2 AND status = 'open'""",
        task_id,
        db.user_id,
    )


async def reopen(task_id):
    pool = db.require_pool()
    await pool.execute(
        """UPDATE tracked_tasks
           SET status = 'open', closed_by = NULL, closed_at = NULL, completion_message_id = NULL, updated_at = now()
           WHERE id = $1 AND user_id = $2 AND status = 'completed'""",
        task_id,
        db.user_id,
    )


async def already_scanned(message_ids):
    pool = db.require_pool()
    rows = await pool.fetch(
        "SELECT message_id FROM scanned_emails WHERE user_id = $1 AND message_id = ANY($2::text[])",
        db.user_id,
        message_ids,
    )
    return {row["message_id"] for row in rows}


async def record_email(message_id, verdict, email_date):
    pool = db.require_pool()
    await pool.execute(
        """INSERT INTO scanned_emails (user_id, message_id, verdict, email_date)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id, message_id) DO NOTHING""",
        db.user_id,
        message_id,
        verdict,
        email_date,
    )


async def create_task(title, company, message_id, request_date, deadline):
    pool = db.require_pool()
    await pool.execute(
        """INSERT INTO tracked_tasks (user_id, title, company, request_message_id, request_date, deadline)
           VALUES ($1, $2, $3, $4, $5, $6)
           ON CONFLICT (user_id, request_message_id) DO NOTHING""",
        db.user_id,
        title,
        company,
        message_id,
        request_date,
        deadline,
    )


async def close_from_email(task_id, message_id):
    pool = db.require_pool()
    await pool.execute(
        """UPDATE tracked_tasks
           SET status = 'completed', closed_by = 'email', closed_at = now(),
               completion_message_id = $3, updated_at = now()
           WHERE id = $1 AND user_id = $2 AND status = 'open'""",
        task_id,
        db.user_id,
        message_id,
    )


async def update_deadline(task_id, deadline):
    pool = db.require_pool()
    await pool.execute(
        "UPDATE tracked_tasks SET deadline = $3, updated_at = now() WHERE id = $1 AND user_id = $2 AND status = 'open'",
        task_id,
        db.user_id,
        deadline,
    )


async def get_scan_state():
    pool = db.require_pool()
    return await pool.fetchrow(
        "SELECT scanned_through, last_scan_at, waiting_count, last_error FROM task_scan_state WHERE user_id = $1",
        db.user_id,
    )


async def save_scan_state(scanned_through, waiting_count, last_error):
    pool = db.require_pool()
    await pool.execute(
        """INSERT INTO task_scan_state (user_id, scanned_through, last_scan_at, waiting_count, last_error)
           VALUES ($1, $2, now(), $3, $4)
           ON CONFLICT (user_id) DO UPDATE
           SET scanned_through = EXCLUDED.scanned_through, last_scan_at = now(),
               waiting_count = EXCLUDED.waiting_count, last_error = EXCLUDED.last_error""",
        db.user_id,
        scanned_through,
        waiting_count,
        last_error,
    )
