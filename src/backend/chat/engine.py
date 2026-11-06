"""One chat reply: offers every enabled integration to the model and runs the tools it asks for."""

import json
import logging
from datetime import datetime

from src.backend.appointment_calls import tool as appointment_call_tool
from src.backend.chat import approvals, system_prompt
from src.backend.chat.model_slot import ModelError
from src.backend.integrations import service
from src.backend.integrations.toolbox import open_toolbox, read_arguments

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
NOT_APPROVED = "The owner did not approve this, so it did not happen. Do not try again unless the owner asks."
OWNER_SENT_A_MESSAGE = (
    "This did not happen, because the owner sent a new message instead of approving. Follow that message. "
    "If this action is still wanted, request it again with any changes."
)
CANNOT_APPROVE_HERE = "This needs the owner's approval, which is only possible in the web app. It did not happen."
TOO_MANY_ROUNDS = "The model used too many tools without finishing its reply."


def assistant_message(text, calls):
    return {
        "role": "assistant",
        "content": text,
        "tool_calls": [
            {
                "id": call["id"],
                "type": "function",
                "function": {"name": call["name"], "arguments": json.dumps(read_arguments(call["arguments"]))},
            }
            for call in calls
        ],
    }


def tool_message(call, result):
    return {"role": "tool", "tool_call_id": call["id"], "content": result}


def current_time_message(now=None):
    """Models don't know today's date, and need it to work out words like "tomorrow"."""
    now = now or datetime.now().astimezone()
    return {"role": "system", "content": f"The owner's current date and time: {now:%A, %B %d, %Y, %H:%M (UTC%z)}."}


def connections_messages(mcp_servers, api_integrations):
    """So the model can answer "what's connected?" without digging through the owner's data to work it out."""
    connections = service.describe_connections(mcp_servers, api_integrations)
    if not connections:
        return []
    return [{"role": "system", "content": f"The owner's connected services: {', '.join(connections)}."}]


async def run_chat(messages, model, can_approve, conversation_id=None):
    """Yields the events the chat page reads: text, tool, approval and error."""
    mcp_servers, api_integrations = await service.load_enabled_integrations()
    async with open_toolbox(mcp_servers, api_integrations) as toolbox:
        await appointment_call_tool.register(toolbox, conversation_id)
        prompt = await system_prompt.load_for_chat()
        owner_prompt = [{"role": "system", "content": prompt}] if prompt.strip() else []
        conversation = [
            *owner_prompt,
            current_time_message(),
            *connections_messages(mcp_servers, api_integrations),
            *messages,
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            text = ""
            calls = []
            try:
                async for event in model.stream(conversation, toolbox.definitions):
                    if event["type"] == "text":
                        text += event["text"]
                        yield {"type": "text", "text": event["text"]}
                    elif event["type"] == "tool_call":
                        calls.append(event)
            except ModelError as error:
                logger.warning("The model failed: %s", error)
                yield {"type": "error", "message": str(error)}
                return

            if not calls:
                return
            conversation.append(assistant_message(text, calls))

            follow_up = None
            for call in calls:
                # Every tool call needs a result before the owner's message can follow, but none may run now.
                if follow_up is not None:
                    conversation.append(tool_message(call, OWNER_SENT_A_MESSAGE))
                    continue
                arguments = read_arguments(call["arguments"])
                if toolbox.needs_approval(call["name"]):
                    if not can_approve:
                        conversation.append(tool_message(call, CANNOT_APPROVE_HERE))
                        continue
                    approval_id, decision = approvals.create()
                    yield {
                        "type": "approval",
                        "id": approval_id,
                        "label": toolbox.label_for(call["name"]),
                        "details": arguments,
                    }
                    answer = await approvals.wait(approval_id, decision)
                    if answer.follow_up is not None:
                        follow_up = answer.follow_up
                        conversation.append(tool_message(call, OWNER_SENT_A_MESSAGE))
                        continue
                    if not answer.approved:
                        conversation.append(tool_message(call, NOT_APPROVED))
                        continue

                label, result = await toolbox.call(call["name"], arguments)
                yield {"type": "tool", "label": label}
                conversation.append(tool_message(call, result))

            if follow_up is not None:
                conversation.append({"role": "user", "content": follow_up})

        yield {"type": "error", "message": TOO_MANY_ROUNDS}
