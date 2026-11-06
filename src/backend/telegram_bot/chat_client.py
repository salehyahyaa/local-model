"""Sends a conversation to the app's /api/chat, which answers in the same format the web page reads."""
import json
import httpx
APP_NOT_RUNNING = "The app isn't running."
APP_STOPPED_RESPONDING = "The app stopped responding."
UNREADABLE_REPLY = "The app sent a reply that couldn't be read."
EMPTY_REPLY = "The model sent an empty reply."
CONNECT_TIMEOUT = 5
HTTP_NOT_FOUND = 404


class ChatError(Exception):
    """Its text is meant to be shown to the owner."""


class ChatClient:
    def __init__(self, app_url, timeout, transport=None):
        self.client = httpx.AsyncClient(
            base_url=app_url,
            timeout=httpx.Timeout(timeout, connect=CONNECT_TIMEOUT),
            transport=transport,
        )

    async def ask(self, messages, conversation_id=None, on_approval=None):
        """Without on_approval, the app refuses anything that needs the owner's approval."""
        body = {"messages": messages, "conversationId": conversation_id, "canApprove": on_approval is not None}
        try:
            async with self.client.stream("POST", "/api/chat", json=body) as response:
                if response.is_error:
                    await response.aread()
                    raise ChatError(read_error(response))
                return await read_reply(response, on_approval)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ChatError(APP_NOT_RUNNING) from None
        except httpx.HTTPError:
            raise ChatError(APP_STOPPED_RESPONDING) from None

    async def answer_approval(self, approval_id, approved):
        return await self.post_answer(approval_id, {"approved": approved})

    async def send_follow_up(self, approval_id, text):
        """Cancels the waiting request and gives the model the owner's message instead."""
        return await self.post_answer(approval_id, {"followUp": text})

    async def post_answer(self, approval_id, answer):
        """Returns False when the request is no longer waiting, such as after it timed out."""
        try:
            response = await self.client.post(f"/api/chat/approvals/{approval_id}", json=answer)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise ChatError(APP_NOT_RUNNING) from None
        except httpx.HTTPError:
            raise ChatError(APP_STOPPED_RESPONDING) from None
        if response.status_code == HTTP_NOT_FOUND:
            return False
        if response.is_error:
            raise ChatError(read_error(response))
        return True

    async def close(self):
        await self.client.aclose()


def read_error(response):
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        error = None
    return error if isinstance(error, str) and error else f"Request failed (HTTP {response.status_code})"


async def read_reply(response, on_approval=None):
    text = ""
    errors = []
    async for line in response.aiter_lines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if event.get("type") == "text":
                text += event["text"]
            elif event.get("type") == "error":
                errors.append(event["message"])
            is_approval = event.get("type") == "approval"
        except (ValueError, AttributeError, KeyError, TypeError):
            raise ChatError(UNREADABLE_REPLY) from None
        if is_approval and on_approval is not None:
            await on_approval(event)
    if errors:
        raise ChatError("\n".join([text, *(f"[Error: {error}]" for error in errors)]).strip())
    if not text.strip():
        raise ChatError(EMPTY_REPLY)
    return text
