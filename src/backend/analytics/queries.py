"""Numbers for the analytics page, read from data the app already keeps. Nothing new is tracked here."""

import json
import logging
from datetime import date, datetime, timedelta, timezone

import asyncpg

from src.backend import db
from src.backend.config import ROOT_DIR
from src.backend.models.embeddings import MODEL_NAME

logger = logging.getLogger(__name__)

EVAL_RESULTS_DIR = ROOT_DIR / "evals" / "results"
EVAL_HISTORY = 20
TOP_TOOLS = 8
OUTCOMES = ("done", "denied", "changed", "failed")
CALL_STATUSES = ("booked", "calling", "needs_review", "not_booked", "failed", "unknown")
VERDICTS = ("task", "same_task", "completion", "neither", "discarded")


async def section(name, read):
    """One missing table or failed query blanks its own section instead of the whole page."""
    try:
        return await read()
    except (asyncpg.UndefinedTableError, asyncpg.UndefinedObjectError):
        return None
    except asyncpg.PostgresError:
        logger.exception("Analytics section %s failed", name)
        return None


async def read_overview(since):
    pool = db.require_pool()
    row = await pool.fetchrow(
        """SELECT count(DISTINCT m.conversation_id) AS chats,
                  count(*) FILTER (WHERE m.role = 'user') AS asked,
                  count(*) FILTER (WHERE m.role = 'assistant') AS answered
           FROM messages m JOIN conversations c ON c.id = m.conversation_id
           WHERE c.user_id = $1 AND m.created_at >= $2""",
        db.user_id,
        since,
    )
    actions = await pool.fetchval(
        """SELECT count(*) FROM tool_activity a JOIN conversations c ON c.id = a.conversation_id
           WHERE c.user_id = $1 AND a.created_at >= $2""",
        db.user_id,
        since,
    )
    all_chats = await pool.fetchval("SELECT count(*) FROM conversations WHERE user_id = $1", db.user_id)
    return {**dict(row), "actions": actions, "allChats": all_chats}


def fill_days(rows, since, until):
    """Every day in the range, so days with nothing still show as zero."""
    found = {row["day"]: row for row in rows}
    days = []
    day = since.date()
    while day <= until.date():
        row = found.get(day)
        days.append({"day": day.isoformat(), "web": row["web"] if row else 0, "telegram": row["telegram"] if row else 0})
        day += timedelta(days=1)
    return days


async def read_daily(since, until):
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT (date_trunc('day', m.created_at))::date AS day,
                  count(*) FILTER (WHERE t.conversation_id IS NULL) AS web,
                  count(*) FILTER (WHERE t.conversation_id IS NOT NULL) AS telegram
           FROM messages m JOIN conversations c ON c.id = m.conversation_id
           LEFT JOIN telegram_conversations t ON t.conversation_id = c.id
           WHERE c.user_id = $1 AND m.role = 'user' AND m.created_at >= $2
           GROUP BY 1 ORDER BY 1""",
        db.user_id,
        since,
    )
    return fill_days(rows, since, until)


async def read_models(since):
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT coalesce(m.model, 'Not recorded') AS model, count(*) AS replies
           FROM messages m JOIN conversations c ON c.id = m.conversation_id
           WHERE c.user_id = $1 AND m.role = 'assistant' AND m.created_at >= $2
           GROUP BY 1 ORDER BY 2 DESC""",
        db.user_id,
        since,
    )
    return [dict(row) for row in rows]


def group_tools(rows):
    """[{tool, done, denied, changed, failed, total}], busiest first, the rest folded into Other."""
    tools = {}
    for row in rows:
        counts = tools.setdefault(row["label"], dict.fromkeys(OUTCOMES, 0))
        counts[row["outcome"]] += row["uses"]
    ranked = sorted(({"tool": label, **counts, "total": sum(counts.values())} for label, counts in tools.items()), key=lambda tool: -tool["total"])
    if len(ranked) <= TOP_TOOLS:
        return ranked
    other = {"tool": "Other", **dict.fromkeys(OUTCOMES, 0), "total": 0}
    for tool in ranked[TOP_TOOLS - 1 :]:
        for key in (*OUTCOMES, "total"):
            other[key] += tool[key]
    return [*ranked[: TOP_TOOLS - 1], other]


async def read_tools(since):
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT a.label, a.outcome, count(*) AS uses
           FROM tool_activity a JOIN conversations c ON c.id = a.conversation_id
           WHERE c.user_id = $1 AND a.created_at >= $2
           GROUP BY 1, 2""",
        db.user_id,
        since,
    )
    tools = group_tools(rows)
    totals = {outcome: sum(tool[outcome] for tool in tools) for outcome in OUTCOMES}
    return {"tools": tools, "totals": totals}


async def read_tasks(since):
    pool = db.require_pool()
    tasks = await pool.fetchrow(
        """SELECT count(*) FILTER (WHERE status = 'open') AS open,
                  count(*) FILTER (WHERE status = 'completed' AND closed_at >= $2) AS completed,
                  count(*) FILTER (WHERE closed_by = 'email' AND closed_at >= $2) AS closed_by_email,
                  count(*) FILTER (WHERE closed_by = 'manual' AND closed_at >= $2) AS closed_by_hand,
                  count(*) FILTER (WHERE created_at >= $2) AS found
           FROM tracked_tasks WHERE user_id = $1""",
        db.user_id,
        since,
    )
    verdicts = await pool.fetch(
        """SELECT verdict, count(*) AS emails FROM scanned_emails
           WHERE user_id = $1 AND created_at >= $2 GROUP BY 1""",
        db.user_id,
        since,
    )
    counted = {row["verdict"]: row["emails"] for row in verdicts}
    return {
        "open": tasks["open"],
        "completed": tasks["completed"],
        "closedByEmail": tasks["closed_by_email"],
        "closedByHand": tasks["closed_by_hand"],
        "found": tasks["found"],
        "emailsChecked": [{"verdict": verdict, "emails": counted.get(verdict, 0)} for verdict in VERDICTS],
    }


async def read_calls(since):
    pool = db.require_pool()
    rows = await pool.fetch(
        """SELECT status, count(*) AS calls FROM appointment_calls
           WHERE user_id = $1 AND created_at >= $2 GROUP BY 1""",
        db.user_id,
        since,
    )
    counted = {row["status"]: row["calls"] for row in rows}
    return [{"status": status, "calls": counted.get(status, 0)} for status in CALL_STATUSES]


async def read_alarms(since):
    pool = db.require_pool()
    row = await pool.fetchrow(
        """SELECT count(*) FILTER (WHERE resolved_at IS NULL) AS active,
                  count(*) FILTER (WHERE started_at >= $2) AS raised,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM resolved_at - started_at))
                      FILTER (WHERE resolved_at IS NOT NULL AND started_at >= $2) AS median_fix_seconds
           FROM alarms WHERE user_id = $1""",
        db.user_id,
        since,
    )
    by_name = await pool.fetch(
        """SELECT name, count(*) AS raised FROM alarms
           WHERE user_id = $1 AND started_at >= $2 GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 6""",
        db.user_id,
        since,
    )
    return {
        "active": row["active"],
        "raised": row["raised"],
        "medianFixSeconds": None if row["median_fix_seconds"] is None else round(row["median_fix_seconds"]),
        "byName": [dict(item) for item in by_name],
    }


async def read_search_coverage():
    """How much of the chat history meaning search can see. None when pgvector isn't set up."""
    pool = db.require_pool()
    row = await pool.fetchrow(
        """SELECT
             (SELECT count(*) FROM messages m JOIN conversations c ON c.id = m.conversation_id
              WHERE c.user_id = $1 AND m.role IN ('user', 'assistant') AND btrim(m.content) <> '') AS messages,
             (SELECT count(DISTINCT e.message_id) FROM search_embeddings e
              JOIN messages m ON m.id = e.message_id JOIN conversations c ON c.id = m.conversation_id
              WHERE c.user_id = $1 AND e.model = $2) AS messages_embedded,
             (SELECT count(*) FROM tool_activity a JOIN conversations c ON c.id = a.conversation_id
              WHERE c.user_id = $1) AS actions,
             (SELECT count(DISTINCT e.tool_activity_id) FROM search_embeddings e
              JOIN tool_activity a ON a.id = e.tool_activity_id JOIN conversations c ON c.id = a.conversation_id
              WHERE c.user_id = $1 AND e.model = $2) AS actions_embedded""",
        db.user_id,
        MODEL_NAME,
    )
    return {
        "model": MODEL_NAME,
        "messages": row["messages"],
        "messagesEmbedded": row["messages_embedded"],
        "actions": row["actions"],
        "actionsEmbedded": row["actions_embedded"],
    }


def answerable(scores, method):
    return (scores.get(method) or {}).get("answerable") or {}


def read_evaluations(results_dir=EVAL_RESULTS_DIR):
    """The latest search evaluation in full, plus a short history of earlier runs."""
    runs = []
    for path in sorted(results_dir.glob("search-*.json")):
        try:
            runs.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            logger.warning("Skipping unreadable evaluation file %s", path.name)
    if not runs:
        return None
    history = [
        {
            "ranAt": run.get("ranAt"),
            "cutoff": (run.get("settings") or {}).get("cutoff"),
            **{method: answerable(run.get("scores") or {}, method).get("recall_at_5") for method in ("words", "meaning", "hybrid")},
            "emptyRate": ((run.get("scores") or {}).get("hybrid", {}).get("nothing") or {}).get("empty_rate"),
        }
        for run in runs[-EVAL_HISTORY:]
    ]
    return {"latest": runs[-1], "history": history}


async def read_theme():
    pool = db.require_pool()
    return await pool.fetchval("SELECT theme FROM user_settings WHERE user_id = $1", db.user_id)


async def collect(days):
    until = datetime.now(timezone.utc).astimezone()
    start = datetime.combine(date.today() - timedelta(days=days - 1), datetime.min.time()).astimezone()
    return {
        "days": days,
        "since": start.isoformat(),
        "theme": await section("theme", read_theme),
        "overview": await section("overview", lambda: read_overview(start)),
        "daily": await section("daily", lambda: read_daily(start, until)),
        "models": await section("models", lambda: read_models(start)),
        "tools": await section("tools", lambda: read_tools(start)),
        "tasks": await section("tasks", lambda: read_tasks(start)),
        "calls": await section("calls", lambda: read_calls(start)),
        "alarms": await section("alarms", lambda: read_alarms(start)),
        "searchCoverage": await section("searchCoverage", read_search_coverage),
        "evaluation": read_evaluations(),
    }
