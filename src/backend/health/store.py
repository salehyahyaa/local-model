from src.backend import db

RECENT_LIMIT = 20
RECENT_DAYS = 7


def row_to_alarm(row):
    return {
        "id": row["id"],
        "key": row["check_key"],
        "name": row["name"],
        "problem": row["problem"],
        "startedAt": row["started_at"].isoformat(),
        "resolvedAt": row["resolved_at"].isoformat() if row["resolved_at"] else None,
    }


async def active_problems():
    """Returns {check_key: problem} for every alarm still open."""
    pool = db.require_pool()
    rows = await pool.fetch(
        "SELECT check_key, problem FROM alarms WHERE user_id = $1 AND resolved_at IS NULL", db.user_id
    )
    return {row["check_key"]: row["problem"] for row in rows}


async def raise_alarm(key, name, problem):
    """Opens an alarm, or updates the text of the one already open for this check."""
    pool = db.require_pool()
    await pool.execute(
        """INSERT INTO alarms (user_id, check_key, name, problem) VALUES ($1, $2, $3, $4)
           ON CONFLICT (user_id, check_key) WHERE resolved_at IS NULL
           DO UPDATE SET name = EXCLUDED.name, problem = EXCLUDED.problem""",
        db.user_id,
        key,
        name,
        problem,
    )


async def resolve_alarm(key):
    pool = db.require_pool()
    await pool.execute(
        "UPDATE alarms SET resolved_at = now() WHERE user_id = $1 AND check_key = $2 AND resolved_at IS NULL",
        db.user_id,
        key,
    )


async def resolve_missing(keys_still_checked):
    """Closes alarms for things that no longer exist, like an integration that was removed."""
    pool = db.require_pool()
    await pool.execute(
        """UPDATE alarms SET resolved_at = now()
           WHERE user_id = $1 AND resolved_at IS NULL AND check_key LIKE 'integration:%'
             AND NOT (check_key = ANY($2::text[]))""",
        db.user_id,
        list(keys_still_checked),
    )


async def list_alarms():
    pool = db.require_pool()
    active = await pool.fetch(
        "SELECT * FROM alarms WHERE user_id = $1 AND resolved_at IS NULL ORDER BY started_at DESC", db.user_id
    )
    resolved = await pool.fetch(
        """SELECT * FROM alarms
           WHERE user_id = $1 AND resolved_at > now() - make_interval(days => $2)
           ORDER BY resolved_at DESC LIMIT $3""",
        db.user_id,
        RECENT_DAYS,
        RECENT_LIMIT,
    )
    return {"active": [row_to_alarm(row) for row in active], "resolved": [row_to_alarm(row) for row in resolved]}
