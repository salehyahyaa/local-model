"""Keeps track of the app's background jobs, so a stopped or failing job raises an alarm."""

JOB_NAMES = {
    "task_scan": "Email To Do scan",
    "call_results": "Phone call results",
    "search_embeddings": "Meaning search",
}

tasks = {}
last_errors = {}


def watch(job, task):
    tasks[job] = task
    last_errors.pop(job, None)


def succeeded(job):
    last_errors.pop(job, None)


def failed(job, problem):
    last_errors[job] = problem


def problems():
    """Returns {job: problem} for every watched job that has stopped or whose last run failed."""
    found = {}
    for job, task in tasks.items():
        if task.done() and not task.cancelled():
            found[job] = "It stopped running. Restart the app to start it again."
        elif job in last_errors:
            found[job] = last_errors[job]
    return found
