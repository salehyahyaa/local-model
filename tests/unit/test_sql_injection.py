import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from scripts.setup_db import quote_ident
from src.backend.main import app

BACKEND_DIR = Path(__file__).resolve().parents[2] / "src" / "backend"
QUERY_METHODS = {"execute", "executemany", "fetch", "fetchrow", "fetchval"}
# The only things allowed inside SQL f-strings: fixed column lists, and "column = $n" built from a fixed field map.
SAFE_SQL_NAMES = {"INTEGRATION_COLUMNS", "SERVER_COLUMNS", "assignments"}
# migrations.py runs the .sql files from db/migrations, which are part of the code.
TRUSTED_FILES = {BACKEND_DIR / "migrations.py"}

client = TestClient(app)


def is_safe_sql(node):
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str)
    if isinstance(node, ast.JoinedStr):
        values = [part.value for part in node.values if isinstance(part, ast.FormattedValue)]
        return all(isinstance(value, ast.Name) and value.id in SAFE_SQL_NAMES for value in values)
    return False


def unsafe_queries(source, filename="<test>"):
    return [
        f"{filename}:{node.lineno}"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in QUERY_METHODS
        and node.args
        and not is_safe_sql(node.args[0])
    ]


def test_backend_never_builds_sql_from_input():
    found = []
    for path in BACKEND_DIR.rglob("*.py"):
        if path not in TRUSTED_FILES:
            found += unsafe_queries(path.read_text(), str(path))
    assert found == []


@pytest.mark.parametrize(
    "query",
    [
        'pool.fetch(f"SELECT * FROM users WHERE name = \'{name}\'")',
        'pool.fetch("SELECT * FROM users WHERE name = \'" + name + "\'")',
        'pool.fetch("SELECT * FROM users WHERE name = \'%s\'" % name)',
        'pool.fetch("SELECT * FROM users WHERE name = \'{}\'".format(name))',
        "pool.fetch(query)",
    ],
)
def test_check_catches_unsafe_queries(query):
    assert unsafe_queries(query)


@pytest.mark.parametrize(
    ("url", "key"),
    [
        ("/api/conversations/7", "title = 'x'; DROP TABLE users; --"),
        ("/api/settings", "theme = 'dark'; DROP TABLE users; --"),
    ],
)
def test_injected_column_names_are_rejected(url, key):
    assert client.patch(url, json={key: "x"}).status_code == 422


def test_quote_ident_escapes_quotes():
    assert quote_ident("local-model") == '"local-model"'
    assert quote_ident('x" SUPERUSER; --') == '"x"" SUPERUSER; --"'
