"""Applies db/migrations/*.sql in order, recording each one in schema_migrations."""

import logging

from src.backend.config import ROOT_DIR

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = ROOT_DIR / "db" / "migrations"


def migration_files():
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


async def ensure_migrations_table(connection):
    await connection.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version     TEXT PRIMARY KEY,
               applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
           )"""
    )


async def applied_versions(connection):
    return {row["version"] for row in await connection.fetch("SELECT version FROM schema_migrations")}


async def mark_applied(connection, version):
    await connection.execute(
        "INSERT INTO schema_migrations (version) VALUES ($1) ON CONFLICT DO NOTHING", version
    )


async def run_pending(connection):
    """Runs every migration not yet in schema_migrations, each in its own transaction. Returns their names."""
    await ensure_migrations_table(connection)
    done = await applied_versions(connection)
    newly_applied = []
    for path in migration_files():
        if path.stem in done:
            continue
        async with connection.transaction():
            await connection.execute(path.read_text())
            await mark_applied(connection, path.stem)
        logger.info("Applied migration %s", path.stem)
        newly_applied.append(path.stem)
    return newly_applied
