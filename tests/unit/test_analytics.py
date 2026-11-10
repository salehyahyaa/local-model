"""The analytics page's data shaping, without a database."""

import asyncio
import json
from datetime import date, datetime

import asyncpg

from src.backend.analytics import queries


def test_days_with_nothing_still_show():
    since, until = datetime(2026, 11, 1), datetime(2026, 11, 3, 12)
    rows = [{"day": date(2026, 11, 2), "web": 3, "telegram": 1}]
    assert queries.fill_days(rows, since, until) == [
        {"day": "2026-11-01", "web": 0, "telegram": 0},
        {"day": "2026-11-02", "web": 3, "telegram": 1},
        {"day": "2026-11-03", "web": 0, "telegram": 0},
    ]


def test_tools_are_counted_by_outcome_and_the_tail_folds_into_other():
    rows = [{"label": f"Tool {n}", "outcome": "done", "uses": 20 - n} for n in range(10)]
    rows.append({"label": "Tool 0", "outcome": "denied", "uses": 5})
    tools = queries.group_tools(rows)
    assert len(tools) == queries.TOP_TOOLS
    assert tools[0] == {"tool": "Tool 0", "done": 20, "denied": 5, "changed": 0, "failed": 0, "total": 25}
    assert tools[-1]["tool"] == "Other"
    assert sum(tool["total"] for tool in tools) == sum(row["uses"] for row in rows)


def test_a_missing_table_blanks_only_its_section():
    async def missing():
        raise asyncpg.UndefinedTableError("no alarms table")

    assert asyncio.run(queries.section("alarms", missing)) is None


def test_evaluations_show_the_latest_run_and_history(tmp_path):
    for number, recall in enumerate([0.6, 0.8]):
        run = {
            "ranAt": f"2026-11-0{number + 1}T10:00:00+00:00",
            "settings": {"cutoff": 0.5},
            "scores": {
                "words": {"answerable": {"recall_at_5": 0.5}},
                "meaning": {"answerable": {"recall_at_5": 0.7}},
                "hybrid": {"answerable": {"recall_at_5": recall}, "nothing": {"empty_rate": 0.9}},
            },
        }
        (tmp_path / f"search-2026110{number + 1}-100000.json").write_text(json.dumps(run))
    (tmp_path / "search-broken.json").write_text("{")
    evaluation = queries.read_evaluations(tmp_path)
    assert evaluation["latest"]["scores"]["hybrid"]["answerable"]["recall_at_5"] == 0.8
    assert [run["hybrid"] for run in evaluation["history"]] == [0.6, 0.8]
    assert evaluation["history"][0]["emptyRate"] == 0.9


def test_no_evaluations_yet(tmp_path):
    assert queries.read_evaluations(tmp_path) is None


def client_with(monkeypatch, collected):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.backend import db
    from src.backend.analytics import routes

    async def collect(days):
        collected.append(days)
        return {"days": days}

    monkeypatch.setattr(db, "pool", object())
    monkeypatch.setattr(db, "user_id", 1)
    monkeypatch.setattr(queries, "collect", collect)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_page_and_data_are_served(monkeypatch):
    collected = []
    client = client_with(monkeypatch, collected)
    page = client.get("/analytics")
    assert page.status_code == 200 and "analytics.js" in page.text
    assert client.get("/api/analytics?days=7").json() == {"days": 7}
    assert collected == [7]


def test_only_known_ranges_are_allowed(monkeypatch):
    client = client_with(monkeypatch, [])
    assert client.get("/api/analytics?days=3").status_code == 422


def test_other_websites_cannot_read_analytics(monkeypatch):
    client = client_with(monkeypatch, [])
    assert client.get("/api/analytics", headers={"origin": "https://evil.example"}).status_code == 403
