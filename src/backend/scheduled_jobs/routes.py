"""The Scheduled page: an overview of scheduled tasks and the background workers that run while the app is open."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from src.backend import config, db
from src.backend.chat import approvals
from src.backend.health import jobs, monitor
from src.backend.health.routes import require_same_origin
from src.backend.scheduled_jobs import repeats, runner, store

router = APIRouter(prefix="/api", dependencies=[Depends(require_same_origin)])

# What each job does and how often it runs. Jobs started in main.py appear here once they are running.
WORKERS = {
    "task_scan": ("Checks Gmail for unfinished work and adds it to To Do.", config.TASK_SCAN_SECONDS),
    "call_results": ("Checks ElevenLabs for the results of appointment calls.", config.APPOINTMENT_CALL_POLL_SECONDS),
    "search_embeddings": ("Indexes new chat messages for meaning search.", config.EMBEDDING_POLL_SECONDS),
    "scheduled_tasks": ("Starts scheduled tasks when they're due.", config.SCHEDULED_TASK_POLL_SECONDS),
}
NOT_FOUND = {"error": "That task doesn't exist."}


def iso(moment):
    return moment.isoformat() if moment else None


def next_run(last, every):
    return iso(last + timedelta(seconds=every)) if last else None


def job_status(job):
    task = jobs.tasks.get(job)
    if task is None:
        return "not running"
    if task.done():
        return "stopped"
    if job in jobs.last_errors:
        return "failing"
    return "running"


def with_run_state(task):
    return {
        **task,
        "repeatLabel": repeats.LABELS.get(task["repeat"], task["repeat"]),
        "isRunning": task["id"] in runner.running,
        "approval": runner.waiting_approvals.get(task["id"]),
    }


def list_workers():
    workers = []
    for job, (description, every) in WORKERS.items():
        last = jobs.last_runs.get(job)
        workers.append({
            "key": job,
            "name": jobs.JOB_NAMES.get(job, job),
            "description": description,
            "everySeconds": every,
            "status": job_status(job),
            "problem": jobs.last_errors.get(job) or jobs.problems().get(job),
            "lastRunAt": iso(last),
            "nextRunAt": next_run(last, every),
        })

    health = monitor.current_status()
    last_check = monitor.last_check_at
    workers.append({
        "key": "health_checks",
        "name": "Health checks",
        "description": "Checks that the app's jobs and integrations are working and raises alarms.",
        "everySeconds": config.HEALTH_CHECK_SECONDS,
        "status": "running" if last_check else "not running",
        "problem": None,
        "lastRunAt": health["lastCheckAt"],
        "nextRunAt": next_run(last_check, config.HEALTH_CHECK_SECONDS),
    })
    return workers


@router.get("/scheduled")
async def list_scheduled():
    tasks = [with_run_state(task) for task in await store.list_tasks()] if db.pool is not None else []
    return {"tasks": tasks, "workers": list_workers()}


def deny_waiting_approval(task_id):
    """Turning a task off or deleting it also answers no to anything it's waiting on."""
    approval = runner.waiting_approvals.get(task_id)
    if approval:
        approvals.resolve(approval["id"], False)


def reactivated_time(task, run_at):
    """A one-off task needs a new future time; a repeating one picks up at its next time from now."""
    now = datetime.now().astimezone()
    if run_at is not None:
        return run_at if run_at > now else None
    current = datetime.fromisoformat(task["nextRunAt"]) if task["nextRunAt"] else None
    if current is None:
        return None
    if current > now:
        return current
    return repeats.next_after(current, task["repeat"], now)


@router.patch("/scheduled/tasks/{task_id}")
async def update_task(task_id: int, request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("isActive"), bool):
        return JSONResponse({"error": "Invalid change"}, status_code=422)
    task = await store.get(task_id)
    if task is None:
        return JSONResponse(NOT_FOUND, status_code=404)

    if not body["isActive"]:
        deny_waiting_approval(task_id)
        updated = await store.set_active(task_id, False, datetime.fromisoformat(task["nextRunAt"]) if task["nextRunAt"] else None)
        return with_run_state(updated)

    run_at = None
    if body.get("runAt") is not None:
        try:
            run_at = datetime.fromisoformat(body["runAt"])
        except (TypeError, ValueError):
            run_at = None
        if run_at is None or run_at.tzinfo is None:
            return JSONResponse({"error": "Invalid time"}, status_code=422)
    next_run = reactivated_time(task, run_at)
    if next_run is None:
        return JSONResponse({"error": "Pick a time in the future to run it again.", "needsTime": True}, status_code=422)
    return with_run_state(await store.set_active(task_id, True, next_run))


@router.delete("/scheduled/tasks/{task_id}")
async def delete_task(task_id: int):
    deny_waiting_approval(task_id)
    if not await store.delete(task_id):
        return JSONResponse(NOT_FOUND, status_code=404)
    return {"ok": True}
