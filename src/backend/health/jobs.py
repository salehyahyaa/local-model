"""Keeps track of the app's background jobs, so a stopped or failing job raises an alarm."""

from datetime import datetime, timezone

JOB_NAMES = {
    "task_scan": "Email To Do scan",
    "call_results": "Phone call results",
    "search_embeddings": "Meaning search",
    "scheduled_tasks": "Scheduled tasks",
}

tasks = {}
last_errors = {}
last_runs = {}


def watch(job, task):
    tasks[job] = task
    last_errors.pop(job, None)


def succeeded(job):
    last_errors.pop(job, None)
    last_runs[job] = datetime.now(timezone.utc)


def failed(job, problem):
    last_errors[job] = problem
    last_runs[job] = datetime.now(timezone.utc)


def problems():
    """Returns {job: problem} for every watched job that has stopped or whose last run failed."""
    found = {}
    for job, task in tasks.items():
        if task.done() and not task.cancelled():
            found[job] = "It stopped running. Restart the app to start it again."
        elif job in last_errors:
            found[job] = last_errors[job]
    return found
