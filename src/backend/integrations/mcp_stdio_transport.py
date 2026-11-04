import asyncio
import json
import logging
import os

from src.backend.integrations.errors import McpError

logger = logging.getLogger(__name__)

MAX_LINE_BYTES = 16 * 1024 * 1024


class McpStdioTransport:
    def __init__(self, command, arguments, environment, timeout):
        self.command = command
        self.arguments = arguments
        self.environment = environment
        self.timeout = timeout
        self.process = None
        self.stderr_task = None

    async def start(self):
        try:
            self.process = await asyncio.create_subprocess_exec(
                self.command,
                *self.arguments,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, **self.environment},
                limit=MAX_LINE_BYTES,
            )
        except OSError as error:
            raise McpError(f"Could not start '{self.command}': {error}") from error
        self.stderr_task = asyncio.create_task(self.log_stderr())

    def set_protocol_version(self, protocol_version):
        pass

    async def log_stderr(self):
        async for line in self.process.stderr:
            logger.debug("[%s] %s", self.command, line.decode(errors="replace").rstrip())

    async def write_message(self, message):
        if self.process.returncode is not None:
            raise McpError(f"'{self.command}' has exited")
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def answer_server_request(self, message):
        if message.get("method") == "ping":
            await self.write_message({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        else:
            error = {"code": -32601, "message": "Method not supported"}
            await self.write_message({"jsonrpc": "2.0", "id": message["id"], "error": error})

    async def read_response(self, request_id):
        while True:
            line = await self.process.stdout.readline()
            if not line:
                raise McpError(f"'{self.command}' closed its output")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Ignoring non-JSON output from %s", self.command)
                continue
            if message.get("id") == request_id and "method" not in message:
                return message
            if "method" in message and "id" in message:
                await self.answer_server_request(message)

    async def send_request(self, message):
        await self.write_message(message)
        try:
            return await asyncio.wait_for(self.read_response(message["id"]), self.timeout)
        except asyncio.TimeoutError as error:
            raise McpError(f"'{self.command}' did not answer in time") from error

    async def send_notification(self, message):
        await self.write_message(message)

    async def close(self):
        if self.process is None:
            return
        if self.process.returncode is None:
            self.process.stdin.close()
            try:
                await asyncio.wait_for(self.process.wait(), 2)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.stderr_task:
            self.stderr_task.cancel()
        self.process = None
