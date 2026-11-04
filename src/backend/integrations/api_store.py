import json

import asyncpg

from src.backend import db
from src.backend.integrations.errors import DuplicateNameError

INTEGRATION_COLUMNS = "id, name, description, method, url, parameters, headers, enabled"


def row_to_integration(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "method": row["method"],
        "url": row["url"],
        "parameters": json.loads(row["parameters"]),
        "headers": json.loads(row["headers"]),
        "enabled": row["enabled"],
    }


async def list_integrations():
    pool = db.require_pool()
    rows = await pool.fetch(
        f"SELECT {INTEGRATION_COLUMNS} FROM api_integrations WHERE user_id = $1 ORDER BY id", db.user_id
    )
    return [row_to_integration(row) for row in rows]


async def list_enabled_integrations():
    return [integration for integration in await list_integrations() if integration["enabled"]]


async def create_integration(integration):
    pool = db.require_pool()
    try:
        row = await pool.fetchrow(
            f"""INSERT INTO api_integrations (user_id, name, description, method, url, parameters, headers)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING {INTEGRATION_COLUMNS}""",
            db.user_id,
            integration["name"],
            integration["description"],
            integration["method"],
            integration["url"],
            json.dumps(integration.get("parameters", [])),
            json.dumps(integration.get("headers", {})),
        )
    except asyncpg.UniqueViolationError as error:
        raise DuplicateNameError(integration["name"]) from error
    return row_to_integration(row)


async def set_enabled(integration_id, enabled):
    pool = db.require_pool()
    result = await pool.execute(
        "UPDATE api_integrations SET enabled = $3, updated_at = now() WHERE id = $1 AND user_id = $2",
        integration_id,
        db.user_id,
        enabled,
    )
    return result != "UPDATE 0"


async def delete_integration(integration_id):
    pool = db.require_pool()
    row = await pool.fetchrow(
        f"DELETE FROM api_integrations WHERE id = $1 AND user_id = $2 RETURNING {INTEGRATION_COLUMNS}",
        integration_id,
        db.user_id,
    )
    return row_to_integration(row) if row else None
