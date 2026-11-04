import logging
import time

import asyncpg

from src.backend.config import (
    DATABASE_HOST,
    DATABASE_NAME,
    DATABASE_PASSWORD,
    DATABASE_PORT,
    DATABASE_URL,
    DATABASE_USER,
)

logger = logging.getLogger(__name__)

LAST_ACCESSED_INTERVAL_SECONDS = 60

pool = None
user_id = None
last_marked_active = 0.0


class DatabaseUnavailableError(Exception):
    """No database password is set, or the database couldn't be reached at startup."""


async def connect():
    global pool, user_id
    if not DATABASE_URL and not DATABASE_PASSWORD:
        logger.warning("No DATABASE_PASSWORD (run scripts/setup_db.py); chats and settings will not be saved")
        return
    try:
        if DATABASE_URL:
            connection_settings = {"dsn": DATABASE_URL}
        else:
            connection_settings = {
                "host": DATABASE_HOST,
                "port": DATABASE_PORT,
                "user": DATABASE_USER,
                "password": DATABASE_PASSWORD,
                "database": DATABASE_NAME,
            }
        pool = await asyncpg.create_pool(**connection_settings, min_size=1, max_size=5)
        user_id = await get_or_create_user()
    except (OSError, asyncpg.PostgresError):
        logger.exception("Could not connect to the database")
        await disconnect()
        return
    logger.info("Connected to the database as user_id=%s", user_id)


async def disconnect():
    global pool, user_id
    if pool:
        await pool.close()
    pool = None
    user_id = None


def require_pool():
    if pool is None or user_id is None:
        raise DatabaseUnavailableError("The database is not connected")
    return pool


async def get_or_create_user():
    """There's no login yet, so the app uses the first user, creating it on first run."""
    async with pool.acquire() as connection, connection.transaction():
        found_id = await connection.fetchval("SELECT user_id FROM users ORDER BY user_id LIMIT 1")
        if found_id is None:
            found_id = await connection.fetchval("INSERT INTO users DEFAULT VALUES RETURNING user_id")
        await connection.execute(
            "INSERT INTO user_settings (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", found_id
        )
        return found_id


async def mark_active():
    """Updates users.last_accessed_at, at most once a minute."""
    global last_marked_active
    if pool is None or user_id is None:
        return
    now = time.monotonic()
    if now - last_marked_active < LAST_ACCESSED_INTERVAL_SECONDS:
        return
    last_marked_active = now
    try:
        await pool.execute("UPDATE users SET last_accessed_at = now() WHERE user_id = $1", user_id)
    except (OSError, asyncpg.PostgresError):
        logger.exception("Could not update last_accessed_at")
