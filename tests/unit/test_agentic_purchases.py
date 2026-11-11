import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from src.backend.agentic_purchases import robinhood, routes, store
from src.backend.main import app

ITEM = {
    "amountMicro": 121480000,
    "declineAckStatus": "UNKNOWN",
    "id": "tx1",
    "merchantDetails": {"merchantName": "Acme Store"},
    "transactionAt": 1794228903000,
    "transactionStatus": "POSTED",
}


def answer(value):
    return json.dumps(value) + "\nHow to interpret the response:\n- notes for the model"


def test_transaction_becomes_a_purchase_row():
    row = robinhood.read_transaction(ITEM)
    assert row["purchase_id"] == "tx1"
    assert row["merchant"] == "Acme Store"
    assert row["total"] == Decimal("121.48")
    assert row["status"] == "POSTED"
    assert row["purchased_at"] == datetime.fromtimestamp(1794228903, tz=timezone.utc)


def test_declined_transaction_keeps_its_reason():
    row = robinhood.read_transaction({**ITEM, "transactionStatus": "DECLINED", "declineReason": "AGENT_PENDING"})
    assert row["status"] == "DECLINED" and row["decline_reason"] == "AGENT_PENDING"


@pytest.mark.parametrize("change", [{"id": None}, {"amountMicro": "12"}, {"merchantDetails": {}}, {"transactionAt": None}])
def test_incomplete_transactions_are_skipped(change):
    assert robinhood.read_transaction({**ITEM, **change}) is None


def test_answer_with_model_notes_is_read():
    assert robinhood.read_result(answer({"a": 1})) == {"a": 1}


@pytest.mark.parametrize("text", ["Error: unauthorized", "not json", answer([1, 2])])
def test_bad_answers_are_reported(text):
    with pytest.raises(robinhood.Unreachable):
        robinhood.read_result(text)


@pytest.mark.parametrize(
    ("server", "expected"),
    [
        ({"transport": "http", "url": "https://banking-agent.robinhood.com/mcp/banking"}, True),
        ({"transport": "http", "url": "https://banking-agent.robinhood.com.evil.example/mcp"}, False),
        ({"transport": "stdio", "url": None}, False),
    ],
)
def test_robinhood_server_is_found_by_its_host(server, expected):
    assert robinhood.is_robinhood(server) is expected


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.closed = False

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "banking_get_agent_card_status":
            return answer({"activation": "ACTIVATED", "cardStatus": "NORMAL"})
        if name == "banking_get_agent_card_balance":
            return answer({"totalSpendMicro": 121480000})
        return answer({"data": {"transactionSearch": self.pages.pop(0)}})

    async def close(self):
        self.closed = True


def test_fetch_reads_every_page_and_never_asks_for_the_card_number(monkeypatch):
    session = FakeSession([
        {"items": [ITEM], "cursor": "next"},
        {"items": [{**ITEM, "id": "tx2"}], "cursor": None},
    ])

    async def open_session(server):
        return session, []

    monkeypatch.setattr(robinhood.toolbox, "open_mcp_session", open_session)
    card, transactions = asyncio.run(robinhood.read_card_activity({"name": "Robinhood Banking"}))
    assert card == {"active": True, "cardStatus": "NORMAL", "spentThisMonth": "121.48"}
    assert [row["purchase_id"] for row in transactions] == ["tx1", "tx2"]
    assert session.closed
    assert all(name != "banking_get_agent_card_creds" for name, _ in session.calls)


def get_page(monkeypatch, server, fetch_result=None, problem=None):
    saved = []

    async def find_server():
        return server

    async def read_card_activity(found):
        if problem:
            raise problem
        return fetch_result

    async def save_purchases(rows):
        saved.extend(rows)

    async def list_purchases():
        return [{"id": 1, "merchant": "Acme Store", "total": "121.48"}]

    monkeypatch.setattr(robinhood, "find_server", find_server)
    monkeypatch.setattr(robinhood, "read_card_activity", read_card_activity)
    monkeypatch.setattr(store, "save_purchases", save_purchases)
    monkeypatch.setattr(store, "list_purchases", list_purchases)
    monkeypatch.setattr(routes, "last_sync", {"at": 0.0, "card": None, "problem": None})
    response = TestClient(app).get("/api/agentic-purchases")
    assert response.status_code == 200
    return response.json(), saved


def test_page_shows_the_connection_and_saves_new_purchases(monkeypatch):
    card = {"active": True, "cardStatus": "NORMAL", "spentThisMonth": "121.48"}
    body, saved = get_page(monkeypatch, {"name": "Robinhood Banking"}, (card, ["row"]))
    assert body["connection"] == {"name": "Robinhood Banking", "card": card, "problem": None}
    assert saved == ["row"]
    assert body["purchases"][0]["merchant"] == "Acme Store"


def test_page_says_when_robinhood_is_not_connected(monkeypatch):
    body, saved = get_page(monkeypatch, None)
    assert body["connection"] is None and saved == []


def test_page_still_shows_saved_purchases_when_robinhood_is_down(monkeypatch):
    body, _ = get_page(monkeypatch, {"name": "Robinhood Banking"}, problem=robinhood.Unreachable("Couldn't reach Robinhood."))
    assert body["connection"]["problem"] == "Couldn't reach Robinhood."
    assert len(body["purchases"]) == 1


def test_sidebar_has_the_tab():
    page = TestClient(app).get("/").text
    assert 'id="agentic-purchases-button"' in page and 'id="agentic-purchases-view"' in page
