import json

import asyncpg

from src.backend import db
from src.backend.integrations.errors import DuplicateNameError

SERVER_COLUMNS = "id, name, transport, url, headers, command, args, env, enabled"


def row_to_server(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "transport": row["transport"],
        "url": row["url"],
        "headers": json.loads(row["headers"]),
        "command": row["command"],
        "args": list(row["args"]),
        "env": json.loads(row["env"]),
        "enabled": row["enabled"],
    }


async def list_servers():
    pool = db.require_pool()
    rows = await pool.fetch(
        f"SELECT {SERVER_COLUMNS} FROM mcp_servers WHERE user_id = $1 ORDER BY id", db.user_id
    )
    return [row_to_server(row) for row in rows]


async def list_enabled_servers():
    return [server for server in await list_servers() if server["enabled"]]


async def create_server(server):
    pool = db.require_pool()
    try:
        row = await pool.fetchrow(
            f"""INSERT INTO mcp_servers (user_id, name, transport, url, headers, command, args, env)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING {SERVER_COLUMNS}""",
            db.user_id,
            server["name"],
            server["transport"],
            server.get("url"),
            json.dumps(server.get("headers", {})),
            server.get("command"),
            server.get("args", []),
            json.dumps(server.get("env", {})),
        )
    except asyncpg.UniqueViolationError as error:
        raise DuplicateNameError(server["name"]) from error
    return row_to_server(row)


async def set_enabled(server_id, enabled):
    pool = db.require_pool()
    result = await pool.execute(
        "UPDATE mcp_servers SET enabled = $3, updated_at = now() WHERE id = $1 AND user_id = $2",
        server_id,
        db.user_id,
        enabled,
    )
    return result != "UPDATE 0"


async def delete_server(server_id):
    pool = db.require_pool()
    row = await pool.fetchrow(
        f"DELETE FROM mcp_servers WHERE id = $1 AND user_id = $2 RETURNING {SERVER_COLUMNS}",
        server_id,
        db.user_id,
    )
    return row_to_server(row) if row else None
