import json
import os
import sys

TOOLS = [
    {
        "name": "add",
        "description": "Adds two numbers",
        "inputSchema": {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}},
    },
    {"name": "read_token", "description": "Returns the TOKEN environment variable", "inputSchema": {"type": "object"}},
]


def handle(message):
    method = message.get("method")
    if method == "initialize":
        return {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake"}}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = message["params"]["name"]
        arguments = message["params"].get("arguments", {})
        if name == "add":
            return {"content": [{"type": "text", "text": str(arguments["a"] + arguments["b"])}]}
        if name == "read_token":
            return {"content": [{"type": "text", "text": os.environ.get("TOKEN", "")}]}
    return None


for line in sys.stdin:
    message = json.loads(line)
    print("log line on stderr", file=sys.stderr, flush=True)
    if "id" not in message:
        continue
    result = handle(message)
    if result is None:
        response = {"jsonrpc": "2.0", "id": message["id"], "error": {"code": -32601, "message": "Unknown"}}
    else:
        response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
    print(json.dumps(response), flush=True)
