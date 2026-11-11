"""The tool the chat model uses to schedule a task. The owner approves it on the usual card before it's saved."""

import logging
from datetime import datetime

import asyncpg

from src.backend import db
from src.backend.integrations.prerequisites import Prerequisite, Prerequisites
from src.backend.scheduled_jobs import repeats, store

logger = logging.getLogger(__name__)

INTEGRATION_NAME = "Scheduled"
ACTION_NAME = "schedule_task"
MAX_TITLE = 120
MAX_INSTRUCTION = 4000
DESCRIPTION = (
    "Schedule a task for you to carry out later, at a set time, once or on repeat. Use only when the owner asks "
    "for something to happen later, like \"text Chris tomorrow at 9am saying ...\" or \"every weekday at 8am email "
    "me my calendar\". If anything the task needs is unclear, such as the time, who it's for or what to say, ask "
    "the owner in the chat first. Never guess. When the task runs you will be given only the instruction, so write "
    "it as a complete request with every detail the owner gave: who, which service, the exact message. Anything "
    "that sends or changes something will still need the owner's approval when it runs."
)
SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "A short name for the task, like \"Text Chris\"."},
        "instruction": {"type": "string", "description": "The full request to carry out when it runs."},
        "run_at": {
            "type": "string",
            "description": "When it first runs. ISO 8601 with a UTC offset, like 2026-11-10T18:00:00-05:00.",
        },
        "repeat": {"type": "string", "enum": repeats.REPEATS, "description": "How often it repeats. once if it doesn't."},
    },
    "required": ["title", "instruction", "run_at", "repeat"],
}
PREREQUISITES = Prerequisites([Prerequisite("run_at", "time", needs="time", from_owner=True)])
NOT_SAVED = "Error: the task was not scheduled. "


def read_time(value):
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo else None


async def schedule(arguments):
    title = str(arguments.get("title") or "").strip()[:MAX_TITLE]
    instruction = str(arguments.get("instruction") or "").strip()
    repeat = arguments.get("repeat") or repeats.ONCE
    run_at = read_time(arguments.get("run_at"))
    if not title or not instruction:
        return f"{NOT_SAVED}It needs a title and an instruction."
    if len(instruction) > MAX_INSTRUCTION:
        return f"{NOT_SAVED}The instruction is too long."
    if repeat not in repeats.REPEATS:
        return f"{NOT_SAVED}repeat must be one of {', '.join(repeats.REPEATS)}."
    if run_at is None:
        return f"{NOT_SAVED}run_at must be an ISO 8601 time with a UTC offset."
    if run_at <= datetime.now().astimezone():
        return f"{NOT_SAVED}That time has already passed. Ask the owner for a time in the future."
    try:
        task = await store.create(title, instruction, repeat, run_at)
    except (db.DatabaseUnavailableError, asyncpg.PostgresError):
        logger.exception("Could not save a scheduled task")
        return f"{NOT_SAVED}The database isn't available."
    logger.info("Scheduled task %s", task["id"])
    when = run_at.astimezone().strftime("%A, %B %d at %-I:%M %p")
    how_often = "" if repeat == repeats.ONCE else f", repeating {repeats.LABELS[repeat].lower()}"
    return f"Scheduled \"{title}\" for {when}{how_often}. It's listed on the Scheduled page."


def register(toolbox):
    """Offered only while the database is connected, since tasks are saved there."""
    if db.pool is None:
        return
    toolbox.add_tool(INTEGRATION_NAME, ACTION_NAME, DESCRIPTION, SCHEMA, schedule, prerequisites=PREREQUISITES)
