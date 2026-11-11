"""Runs scheduled tasks when they're due, each in a new chat, while the app is open.

A task that was due while the app was closed runs once when it opens again; a repeating one then moves on to its
next time. Anything a task does that needs approval waits on the Scheduled page until the owner answers.
"""

import asyncio
import logging
from datetime import datetime

from src.backend import config, store as chat_store
from src.backend.chat import engine, model_slot
from src.backend.health import jobs
from src.backend.scheduled_jobs import repeats, store

logger = logging.getLogger(__name__)

JOB = "scheduled_tasks"
# Long enough to answer when you're back at the Mac, since nobody is watching the chat when a task runs.
APPROVAL_TIMEOUT = 12 * 60 * 60
NO_MODEL = "No model is connected."

running = {}
waiting_approvals = {}


def run_message(task):
    return {
        "role": "user",
        "content": f"This is a scheduled task I set up earlier, called \"{task['title']}\". Do it now:\n\n"
                   f"{task['instruction']}",
    }


async def start_conversation(task):
    conversation = await chat_store.create_conversation()
    conversation_id = conversation["id"]
    await chat_store.update_conversation(conversation_id, {"title": f"Scheduled: {task['title']}"})
    return conversation_id


async def run_task(task):
    ran_at = datetime.now().astimezone()
    next_run = repeats.next_after(datetime.fromisoformat(task["nextRunAt"]), task["repeat"], ran_at)
    conversation_id = None
    status = "failed"
    try:
        conversation_id = await start_conversation(task)
        message = run_message(task)
        await chat_store.add_message(conversation_id, "user", message["content"])
        model = model_slot.connected_model
        if model is None:
            await chat_store.add_message(conversation_id, "assistant", NO_MODEL)
        else:
            reply = ""
            failed = False
            events = engine.run_chat(
                [message], model, True, conversation_id, approval_timeout=APPROVAL_TIMEOUT
            )
            async for event in events:
                if event["type"] == "text":
                    reply += event["text"]
                elif event["type"] == "approval":
                    waiting_approvals[task["id"]] = {"id": event["id"], "actions": event["actions"]}
                elif event["type"] == "tool":
                    waiting_approvals.pop(task["id"], None)
                elif event["type"] == "error":
                    reply += ("\n\n" if reply else "") + event["message"]
                    failed = True
            await chat_store.add_message(conversation_id, "assistant", reply or "Done.")
            status = "failed" if failed else "completed"
    except Exception:
        logger.exception("Scheduled task %s failed", task["id"])
    finally:
        waiting_approvals.pop(task["id"], None)
        try:
            await store.finish_run(task["id"], ran_at, status, conversation_id, next_run)
        except Exception:
            logger.exception("Could not save the result of scheduled task %s", task["id"])
        running.pop(task["id"], None)
    logger.info("Scheduled task %s %s", task["id"], status)


async def start_due_tasks():
    for task in await store.due_tasks(datetime.now().astimezone()):
        if task["id"] not in running:
            running[task["id"]] = asyncio.create_task(run_task(task))


async def run():
    while True:
        try:
            await start_due_tasks()
            jobs.succeeded(JOB)
        except Exception:
            logger.exception("Could not check for due scheduled tasks")
            jobs.failed(JOB, "The last check hit an error. See logs/app.log.")
        await asyncio.sleep(config.SCHEDULED_TASK_POLL_SECONDS)
