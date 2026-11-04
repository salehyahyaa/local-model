"""One-time, production-style setup of the local "local-model" database. Run it yourself:

    venv/bin/python -m scripts.setup_db

What it does (safe to run again):
  1. Creates two login roles with random passwords:
       local_model_owner  owns the tables and runs migrations
       local_model_app    what the app logs in as; can only read/write rows
  2. Moves ownership of the existing tables to local_model_owner and locks down default access.
  3. Runs pending migrations in db/migrations as local_model_owner (tracked in schema_migrations).
  4. Requires a password (scram-sha-256) for these two roles in pg_hba.conf, for this database only.
  5. Stores the passwords, and the Deepgram key from .env, in the OS keychain, then removes
     DEEPGRAM_API_KEY from .env. No secret is ever printed.

It connects as your own OS user (the Postgres superuser on a Homebrew install) over the local socket.
"""

import asyncio
import getpass
import secrets
import sys

import asyncpg
from dotenv import dotenv_values

from src.backend import migrations
from src.backend.config import (
    DATABASE_HOST,
    DATABASE_NAME,
    DATABASE_OWNER_USER,
    DATABASE_PORT,
    DATABASE_USER,
    ENV_FILE,
)
from src.backend.secret_store import SERVICE_NAME, get_secret, set_secret

HBA_MARKER = "# local-model: password required for app roles"

# Used once, when schema_migrations is first created on a database that already has tables:
# records which migrations were already applied by hand, so they aren't run twice.
ALREADY_APPLIED_CHECKS = {
    "001_users_and_mcp_servers": "SELECT to_regclass('public.mcp_servers') IS NOT NULL",
    "002_conversations_and_settings": "SELECT to_regclass('public.conversations') IS NOT NULL",
    "003_api_integrations": "SELECT to_regclass('public.api_integrations') IS NOT NULL",
    "004_users_user_id_and_last_accessed": """SELECT EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'user_id')""",
}


def step(message):
    print(f"• {message}")


async def quote_literal(connection, value):
    return await connection.fetchval("SELECT quote_literal($1)", value)


async def ensure_role(admin, role_name, secret_name):
    """Creates or updates the role with a password, keeping the keychain and the database in sync."""
    password = get_secret(secret_name) or secrets.token_urlsafe(32)
    password_literal = await quote_literal(admin, password)
    exists = await admin.fetchval("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = $1)", role_name)
    verb = "ALTER" if exists else "CREATE"
    await admin.execute(f'{verb} ROLE "{role_name}" LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {password_literal}')
    set_secret(secret_name, password)
    step(f"Role {role_name} {'updated' if exists else 'created'}; password stored in the keychain")
    return password


async def take_ownership(admin):
    await admin.execute(f'ALTER DATABASE "{DATABASE_NAME}" OWNER TO "{DATABASE_OWNER_USER}"')
    await admin.execute(f'ALTER SCHEMA public OWNER TO "{DATABASE_OWNER_USER}"')
    tables = await admin.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    for table in tables:
        await admin.execute(f'ALTER TABLE public."{table["tablename"]}" OWNER TO "{DATABASE_OWNER_USER}"')
    await admin.execute(f'REVOKE ALL ON DATABASE "{DATABASE_NAME}" FROM PUBLIC')
    await admin.execute(f'GRANT CONNECT ON DATABASE "{DATABASE_NAME}" TO "{DATABASE_USER}"')
    await admin.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    step(f"{len(tables)} existing table(s) now owned by {DATABASE_OWNER_USER}; public access revoked")


async def record_already_applied(owner):
    await migrations.ensure_migrations_table(owner)
    if await migrations.applied_versions(owner):
        return
    for version, check in ALREADY_APPLIED_CHECKS.items():
        if await owner.fetchval(check):
            await migrations.mark_applied(owner, version)
            step(f"Recorded {version} as already applied")


async def grant_app_access(owner):
    app = f'"{DATABASE_USER}"'
    await owner.execute(f"GRANT USAGE ON SCHEMA public TO {app}")
    await owner.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app}")
    await owner.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app}")
    await owner.execute(f"REVOKE ALL ON schema_migrations FROM {app}")
    await owner.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app}"
    )
    await owner.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {app}")
    step(f"{DATABASE_USER} can read/write rows only (no CREATE, ALTER or DROP)")


async def require_passwords(admin):
    hba_path = await admin.fetchval("SHOW hba_file")
    with open(hba_path) as hba_file:
        current = hba_file.read()
    if HBA_MARKER not in current:
        roles = f"{DATABASE_USER},{DATABASE_OWNER_USER}"
        rules = (
            f"{HBA_MARKER}\n"
            f'host    "{DATABASE_NAME}"    {roles}    127.0.0.1/32    scram-sha-256\n'
            f'host    "{DATABASE_NAME}"    {roles}    ::1/128         scram-sha-256\n\n'
        )
        with open(hba_path, "w") as hba_file:
            hba_file.write(rules + current)
    await admin.execute("SELECT pg_reload_conf()")
    errors = await admin.fetch("SELECT line_number, error FROM pg_hba_file_rules WHERE error IS NOT NULL")
    if errors:
        sys.exit(f"pg_hba.conf has errors after editing {hba_path}: {[dict(error) for error in errors]}")
    step(f"Passwords required for the app roles ({hba_path})")


def move_deepgram_key():
    if get_secret("DEEPGRAM_API_KEY") and not dotenv_values(ENV_FILE).get("DEEPGRAM_API_KEY"):
        step("Deepgram key already in the keychain")
        return
    key = dotenv_values(ENV_FILE).get("DEEPGRAM_API_KEY")
    if not key and sys.stdin.isatty():
        key = getpass.getpass("Deepgram API key (hidden, Enter to skip): ")
    if not key:
        step("Deepgram key skipped")
        return
    set_secret("DEEPGRAM_API_KEY", key.strip())
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text().splitlines(keepends=True)
        ENV_FILE.write_text("".join(line for line in lines if not line.startswith("DEEPGRAM_API_KEY=")))
    step("Deepgram key stored in the keychain and removed from .env")


async def connect_as(user, password):
    return await asyncpg.connect(
        host=DATABASE_HOST, port=DATABASE_PORT, user=user, password=password, database=DATABASE_NAME
    )


async def main():
    admin = await asyncpg.connect(database=DATABASE_NAME, user=getpass.getuser())
    try:
        owner_password = await ensure_role(admin, DATABASE_OWNER_USER, "DATABASE_OWNER_PASSWORD")
        app_password = await ensure_role(admin, DATABASE_USER, "DATABASE_PASSWORD")
        await take_ownership(admin)
        await require_passwords(admin)
    finally:
        await admin.close()

    owner = await connect_as(DATABASE_OWNER_USER, owner_password)
    try:
        await record_already_applied(owner)
        applied = await migrations.run_pending(owner)
        step(f"Migrations applied: {', '.join(applied) or 'none pending'}")
        await grant_app_access(owner)
    finally:
        await owner.close()

    app = await connect_as(DATABASE_USER, app_password)
    try:
        tables = await app.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
        )
        step(f"App login works; tables: {', '.join(row['tablename'] for row in tables)}")
    finally:
        await app.close()

    move_deepgram_key()
    print(f"\nDone. Secrets are in the keychain under service '{SERVICE_NAME}'.")


if __name__ == "__main__":
    asyncio.run(main())
