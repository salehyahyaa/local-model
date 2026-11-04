import json

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

EXPECTED_TOKEN = "Bearer test-token"

app = FastAPI()


def mcp_result(message):
    method = message.get("method")
    if method == "initialize":
        return {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake-http"}}
    if method == "tools/list":
        return {"tools": [{"name": "echo", "description": "Echoes text", "inputSchema": {"type": "object"}}]}
    if method == "tools/call":
        return {"content": [{"type": "text", "text": message["params"]["arguments"].get("text", "")}]}
    return {}


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    if request.headers.get("authorization") != EXPECTED_TOKEN:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    message = await request.json()
    if "id" not in message:
        return Response(status_code=202)
    response = {"jsonrpc": "2.0", "id": message["id"], "result": mcp_result(message)}
    headers = {"Mcp-Session-Id": "fake-session"}
    if message["method"] == "tools/call":
        body = f"event: message\ndata: {json.dumps(response)}\n\n"
        return Response(body, media_type="text/event-stream", headers=headers)
    return JSONResponse(response, headers=headers)


@app.delete("/mcp")
async def end_session():
    return Response(status_code=204)


@app.get("/weather/{city}")
async def weather(city: str, request: Request, units: str = "metric"):
    if request.headers.get("x-api-key") != "weather-key":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"city": city, "units": units, "forecast": "sunny"}
