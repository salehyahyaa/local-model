"""Finds unfinished work in Gmail: an email asking for something stays open until a later email shows it's done.

Mail is opened read-only, so nothing is marked as read or changed. Logs hold counts only, never email content.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import partial

from src.backend import config
from src.backend.chat import model_slot
from src.backend.chat.model_slot import ModelError
from src.backend.integrations import env_secrets, mcp_store
from src.backend.integrations.gmail import mailbox
from src.backend.integrations.gmail.mailbox import GmailError
from src.backend.integrations.service import GMAIL_SERVER_ARGS
from src.backend.task_tracker import classifier, store

logger = logging.getLogger(__name__)

FIRST_SCAN_DAYS = 90
WEEK_DAYS = 7
SEARCH_LIMIT = 500
SCAN_FAILED_MESSAGE = "Couldn't check Gmail. It will try again shortly."
MODEL_FAILED_MESSAGE = "The model couldn't check your emails. It will try again shortly."

scan_lock = asyncio.Lock()


async def find_server_environment(server_args):
    for server in await mcp_store.list_enabled_servers():
        if server["args"] == server_args:
            return env_secrets.resolve_mapping(server["env"])
    return None


async def is_gmail_connected():
    return any(server["args"] == GMAIL_SERVER_ARGS for server in await mcp_store.list_enabled_servers())


def build_query(start, end):
    """Gmail reads these dates in its own timezone, so each side has a day's margin. Repeats are skipped later."""
    after = start - timedelta(days=1)
    before = end + timedelta(days=1)
    return f"after:{after:%Y/%m/%d} before:{before:%Y/%m/%d} -from:me -category:promotions -category:social"


def read_headers(address, password, query):
    with mailbox.open_all_mail(address, password, readonly=True) as connection:
        return mailbox.search(connection, query, SEARCH_LIMIT)


def read_body(address, password, email_id):
    with mailbox.open_all_mail(address, password, readonly=True) as connection:
        messages = mailbox.read(connection, [email_id])
    return messages[0]["body"] if messages else ""


def read_email_date(email):
    try:
        parsed = parsedate_to_datetime(email["date"])
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def prepare(email):
    return {
        **email,
        "message_id": email["message_id"] or f"uid:{email['id']}",
        "email_date": read_email_date(email),
    }


async def find_new_emails(address, password, start, end):
    """Oldest first, so a confirmation always comes after the request it answers."""
    found = await asyncio.to_thread(read_headers, address, password, build_query(start, end))
    if len(found) >= SEARCH_LIMIT:
        logger.warning("Task scan reached its limit of %s emails in one week", SEARCH_LIMIT)
    emails = [prepare(email) for email in found]
    seen = await store.already_scanned([email["message_id"] for email in emails])
    return sorted(
        (email for email in emails if email["message_id"] not in seen), key=lambda email: email["email_date"]
    )


async def apply_decision(email, decision):
    answer = decision["answer"]
    if answer == "new_task":
        await store.create_task(
            decision["title"], decision["company"], email["message_id"], email["email_date"], decision["deadline"]
        )
        verdict = "task"
    elif answer == "completes":
        await store.close_from_email(decision["task_id"], email["message_id"])
        verdict = "completion"
    elif answer == "same_task":
        if decision["deadline"]:
            await store.update_deadline(decision["task_id"], decision["deadline"])
        verdict = "same_task"
    else:
        verdict = "neither" if answer == "neither" else "discarded"
    await store.record_email(email["message_id"], verdict, email["email_date"])
    return verdict


async def judge_emails(emails, model, address, password, budget):
    """Returns how many were judged. A model failure propagates, so the next scan picks up from that same email."""
    judged = 0
    for email in emails[:budget]:
        tasks = await store.tasks_for_model()
        fetch_body = partial(asyncio.to_thread, read_body, address, password, email["id"])
        decision = await classifier.judge(model, email, tasks, fetch_body)
        await apply_decision(email, decision)
        judged += 1
    return judged


async def scan_gmail():
    environment = await find_server_environment(GMAIL_SERVER_ARGS)
    if environment is None:
        return
    address, password = environment["GMAIL_ADDRESS"], environment["GMAIL_APP_PASSWORD"]

    state = await store.get_scan_state()
    today = datetime.now(timezone.utc).date()
    saved = state["scanned_through"] if state else None
    start = saved or today - timedelta(days=FIRST_SCAN_DAYS)
    model = model_slot.connected_model

    if model is None:
        waiting = await find_new_emails(address, password, start, min(start + timedelta(days=WEEK_DAYS), today))
        await store.save_scan_state(saved, len(waiting), None)
        return

    budget = config.TASK_MODEL_EMAILS_PER_SCAN
    judged_total = 0
    while True:
        end = min(start + timedelta(days=WEEK_DAYS), today)
        emails = await find_new_emails(address, password, start, end)
        try:
            judged = await judge_emails(emails, model, address, password, budget)
        except ModelError:
            await store.save_scan_state(start, len(emails), MODEL_FAILED_MESSAGE)
            raise
        budget -= judged
        judged_total += judged
        if judged < len(emails):
            await store.save_scan_state(start, len(emails) - judged, None)
            break
        # The date only moves once a whole week is judged, so unfinished emails are found by the next search.
        start = end
        if end >= today or budget <= 0:
            await store.save_scan_state(start, 0, None)
            break
    logger.info("Task scan judged %s emails", judged_total)


async def save_failure(message):
    state = await store.get_scan_state()
    await store.save_scan_state(
        state["scanned_through"] if state else None, state["waiting_count"] if state else 0, message
    )


async def scan():
    """Runs one scan at a time. A failure is saved for the panel to show, and the next scan tries again."""
    async with scan_lock:
        try:
            await scan_gmail()
        except ModelError:
            logger.warning("Task scan stopped: the model couldn't answer")
        except GmailError as error:
            logger.warning("Task scan failed: %s", type(error).__name__)
            await save_failure(str(error))
        except OSError as error:
            logger.warning("Task scan could not reach Gmail: %s", type(error).__name__)
            await save_failure(SCAN_FAILED_MESSAGE)


def is_scanning():
    return scan_lock.locked()
