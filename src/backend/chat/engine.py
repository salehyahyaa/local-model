"""One chat reply: offers every enabled integration to the model and runs the tools it asks for."""

import json
import logging
from datetime import datetime

from src.backend.appointment_calls import connection as appointment_call_connection
from src.backend.appointment_calls import tool as appointment_call_tool
from src.backend.chat import approvals, system_prompt
from src.backend.chat.model_slot import ModelError
from src.backend.chat_memory import activity, errors, search
from src.backend.integrations import service
from src.backend.integrations.prerequisites import missing_message
from src.backend.integrations.toolbox import is_error_result, open_toolbox, read_arguments
from src.backend.scheduled_jobs import tool as scheduled_tool

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8
NOT_APPROVED = (
    "The owner tapped Deny, so this did not happen. Tell the owner it was denied and not done, without saying it "
    "still needs approval. Do not try again unless the owner asks."
)
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


def integration_logos(mcp_servers, api_integrations):
    """What the approval card needs to show each integration's logo. Never addresses or keys."""
    logos = {appointment_call_connection.NAME: {"name": appointment_call_connection.NAME, "kind": "phone"}}
    for server in mcp_servers:
        public = service.public_mcp_server(server)
        logos[public["name"]] = {
            "name": public["name"],
            **({"provider": public["provider"]} if "provider" in public else {}),
        }
    for integration in api_integrations:
        logos[integration["name"]] = {"name": integration["name"]}
    return logos


async def run_chat(
    messages, model, can_approve, conversation_id=None, from_telegram=False, approval_timeout=None
):
    """Yields the events the chat page reads: text, tool, approval and error."""
    mcp_servers, api_integrations = await service.load_enabled_integrations()
    async with open_toolbox(mcp_servers, api_integrations) as toolbox:
        await appointment_call_tool.register(toolbox, conversation_id)
        search.register(toolbox)
        scheduled_tool.register(toolbox)
        logos = integration_logos(mcp_servers, api_integrations)
        prompt = await system_prompt.load_for_chat()
        owner_prompt = [{"role": "system", "content": prompt}] if prompt.strip() else []
        if from_telegram:
            owner_prompt.append({"role": "system", "content": system_prompt.TELEGRAM_PROMPT})
        conversation = [
            *owner_prompt,
            current_time_message(),
            *connections_messages(mcp_servers, api_integrations),
            *activity.actions_message(await activity.load(conversation_id)),
            *messages,
        ]

        async def remember(call, arguments, outcome, result):
            label = toolbox.label_for(call["name"])
            logger.info(
                "Model called %s with %s: %s", call["name"], json.dumps(arguments, ensure_ascii=False), outcome
            )
            # Searching memory isn't something the owner asked to be remembered, and would only clutter it.
            if label == search.LABEL:
                return
            await activity.record(conversation_id, label, arguments, outcome, result)

        def owner_text():
            # Only the owner's own messages, never tool results, so a value can't come from an email or the model.
            return "\n".join(message["content"] for message in conversation if message["role"] == "user")

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
                await errors.record(
                    errors.CHAT, type(error).__name__, str(error), "writing a reply", conversation_id
                )
                yield {"type": "error", "message": str(error)}
                return

            if not calls:
                return
            conversation.append(assistant_message(text, calls))

            # A tool still missing information from the owner never runs or reaches the card; the model asks instead.
            missing = {
                call["id"]: toolbox.missing_info(
                    call["name"], read_arguments(call["arguments"]), owner_text(), datetime.now().astimezone()
                )
                for call in calls
            }
            # Everything else in this step that needs approval goes on one card, so the owner answers once.
            needing = [call for call in calls if toolbox.needs_approval(call["name"]) and not missing[call["id"]]]
            answer = None
            if needing and can_approve:
                approval_id, decision = approvals.create()
                yield {
                    "type": "approval",
                    "id": approval_id,
                    "actions": [
                        {
                            "label": toolbox.label_for(call["name"]),
                            "details": read_arguments(call["arguments"]),
                            "integration": logos.get(
                                toolbox.integration_for(call["name"]), {"name": toolbox.integration_for(call["name"])}
                            ),
                        }
                        for call in needing
                    ],
                }
                answer = await approvals.wait(approval_id, decision, approval_timeout)

            follow_up = answer.follow_up if answer is not None else None
            for call in calls:
                # Every tool call needs a result before the owner's message can follow, but none may run now.
                arguments = read_arguments(call["arguments"])
                if follow_up is not None:
                    conversation.append(tool_message(call, OWNER_SENT_A_MESSAGE))
                    await remember(call, arguments, activity.CHANGED, None)
                    continue
                if missing[call["id"]]:
                    result = missing_message(missing[call["id"]])
                    conversation.append(tool_message(call, result))
                    await remember(call, arguments, activity.FAILED, result)
                    continue
                if call in needing:
                    if not can_approve:
                        conversation.append(tool_message(call, CANNOT_APPROVE_HERE))
                        await remember(call, arguments, activity.DENIED, CANNOT_APPROVE_HERE)
                        continue
                    if not answer.approved:
                        conversation.append(tool_message(call, NOT_APPROVED))
                        await remember(call, arguments, activity.DENIED, None)
                        continue

                label, result = await toolbox.call(call["name"], arguments)
                yield {"type": "tool", "label": label}
                conversation.append(tool_message(call, result))
                outcome = activity.FAILED if is_error_result(result) else activity.DONE
                await remember(call, arguments, outcome, result)

            if follow_up is not None:
                conversation.append({"role": "user", "content": follow_up})

        await errors.record(errors.CHAT, "TooManyToolRounds", TOO_MANY_ROUNDS, "writing a reply", conversation_id)
        yield {"type": "error", "message": TOO_MANY_ROUNDS}
