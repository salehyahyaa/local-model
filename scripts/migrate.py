"""Runs pending migrations as the owner role:  venv/bin/python -m scripts.migrate"""

import asyncio

import asyncpg

from src.backend import migrations
from src.backend.config import DATABASE_HOST, DATABASE_NAME, DATABASE_OWNER_USER, DATABASE_PORT
from src.backend.secret_store import get_secret


async def main():
    owner = await asyncpg.connect(
        host=DATABASE_HOST,
        port=DATABASE_PORT,
        user=DATABASE_OWNER_USER,
        password=get_secret("DATABASE_OWNER_PASSWORD"),
        database=DATABASE_NAME,
    )
    try:
        applied = await migrations.run_pending(owner)
    finally:
        await owner.close()
    print(f"Migrations applied: {', '.join(applied) or 'none pending'}")


if __name__ == "__main__":
    asyncio.run(main())
