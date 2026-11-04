import asyncio
import socket
import threading
import time
from pathlib import Path

import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT_DIR / "db" / "schema.sql"
PROTECTED_DATABASE_NAMES = {"local-model"}


def find_free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_port(port, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise TimeoutError(f"Nothing started on port {port}")


class BackgroundServer:
    def __init__(self, app):
        self.port = find_free_port()
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        self.thread.start()
        wait_for_port(self.port)

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


def reset_test_database(database_url):
    import asyncpg

    async def reset():
        connection = await asyncpg.connect(database_url)
        try:
            database_name = await connection.fetchval("SELECT current_database()")
            if database_name in PROTECTED_DATABASE_NAMES:
                raise RuntimeError(f"Refusing to reset the '{database_name}' database; use a separate test database")
            await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            await connection.execute(SCHEMA_FILE.read_text())
        finally:
            await connection.close()

    asyncio.run(reset())
