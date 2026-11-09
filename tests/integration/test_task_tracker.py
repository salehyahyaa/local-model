"""The To Do list against a real database, with a fake model and fake Gmail."""

import json
from datetime import date

from src.backend import db
from src.backend.integrations import mcp_store
from src.backend.integrations.service import GMAIL_SERVER_ARGS
from src.backend.task_tracker import scanner, store
from tests.integration.test_appointment_calls import run_with_database


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = list(replies)

    async def stream(self, messages, tools):
        yield {"type": "text", "text": json.dumps(self.replies.pop(0))}


def make_email(number, day):
    return {
        "id": str(number),
        "message_id": f"<{number}@x>",
        "from": "people@acme.com",
        "subject": f"Subject {number}",
        "date": f"{day:02d} Oct 2026 10:00:00 +0000",
    }


def setup_scan(monkeypatch, emails, model):
    async def find_environment(args):
        assert args == GMAIL_SERVER_ARGS
        return {"GMAIL_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "secret"}

    monkeypatch.setattr(scanner, "find_server_environment", find_environment)
    monkeypatch.setattr(scanner, "read_headers", lambda address, password, query: emails)
    monkeypatch.setattr(scanner.model_slot, "connected_model", model)


NEW_TASK = {"answer": "new_task", "title": "Sign the offer", "company": "Acme", "deadline": "2030-01-05"}


def test_a_task_stays_open_until_a_confirmation_closes_it(test_database_url, monkeypatch):
    async def scenario():
        setup_scan(monkeypatch, [make_email(1, 1)], ScriptedModel(NEW_TASK))
        await scanner.scan()
        tasks = await store.list_tasks()
        assert [task["title"] for task in tasks["open"]] == ["Sign the offer"]
        assert tasks["open"][0]["deadline"] == "2030-01-05"
        task_id = tasks["open"][0]["id"]

        answer = {"answer": "completes", "task_id": task_id}
        setup_scan(monkeypatch, [make_email(1, 1), make_email(2, 2)], ScriptedModel(answer))
        await scanner.scan()
        tasks = await store.list_tasks()
        assert tasks["open"] == []
        assert tasks["completed"][0]["closedBy"] == "email"

    run_with_database(test_database_url, monkeypatch, scenario)


def test_a_reminder_updates_the_task_without_listing_it_twice(test_database_url, monkeypatch):
    async def scenario():
        setup_scan(monkeypatch, [make_email(1, 1)], ScriptedModel(NEW_TASK))
        await scanner.scan()
        task_id = (await store.list_tasks())["open"][0]["id"]

        answer = {"answer": "same_task", "task_id": task_id, "deadline": "2030-02-01"}
        setup_scan(monkeypatch, [make_email(2, 2)], ScriptedModel(answer))
        await scanner.scan()
        tasks = await store.list_tasks()
        assert len(tasks["open"]) == 1
        assert tasks["open"][0]["deadline"] == "2030-02-01"

    run_with_database(test_database_url, monkeypatch, scenario)


def test_mark_done_and_undo_survive_later_scans(test_database_url, monkeypatch):
    async def scenario():
        setup_scan(monkeypatch, [make_email(1, 1)], ScriptedModel(NEW_TASK))
        await scanner.scan()
        task_id = (await store.list_tasks())["open"][0]["id"]

        await store.mark_done(task_id)
        setup_scan(monkeypatch, [make_email(1, 1)], ScriptedModel())  # the same email must not be judged again
        await scanner.scan()
        tasks = await store.list_tasks()
        assert tasks["open"] == []
        assert tasks["completed"][0]["closedBy"] == "manual"

        await store.reopen(task_id)
        await scanner.scan()
        assert (await store.list_tasks())["open"][0]["id"] == task_id

    run_with_database(test_database_url, monkeypatch, scenario)


def test_a_reminder_about_something_marked_done_stays_closed(test_database_url, monkeypatch):
    async def scenario():
        setup_scan(monkeypatch, [make_email(1, 1)], ScriptedModel(NEW_TASK))
        await scanner.scan()
        task_id = (await store.list_tasks())["open"][0]["id"]
        await store.mark_done(task_id)

        answer = {"answer": "same_task", "task_id": task_id, "deadline": "2031-01-01"}
        setup_scan(monkeypatch, [make_email(2, 2)], ScriptedModel(answer))
        await scanner.scan()
        tasks = await store.list_tasks()
        assert tasks["open"] == []
        assert tasks["completed"][0]["deadline"] == "2030-01-05"

    run_with_database(test_database_url, monkeypatch, scenario)


def test_scanning_moves_forward_and_saves_its_place(test_database_url, monkeypatch):
    async def scenario():
        setup_scan(monkeypatch, [], ScriptedModel())
        await scanner.scan()
        state = await store.get_scan_state()
        assert state["scanned_through"] > date(2026, 1, 1)
        assert state["waiting_count"] == 0
        assert await db.pool.fetchval("SELECT count(*) FROM scanned_emails") == 0
        assert await mcp_store.list_enabled_servers() == []

    run_with_database(test_database_url, monkeypatch, scenario)
