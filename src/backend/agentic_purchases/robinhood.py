"""Reads the Robinhood agentic card through the Robinhood Banking MCP server added from the + menu.

Only read-only tools are used here. The card number is never fetched by this module.
"""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse

from src.backend.integrations import mcp_store, toolbox

logger = logging.getLogger(__name__)

PROVIDER = "robinhood"
HOST = "banking-agent.robinhood.com"
PAGE_SIZE = 50
MAX_PAGES = 10
MICRO = Decimal("1000000")


class NotConnected(Exception):
    """Robinhood Banking isn't added and turned on in the + menu."""


class Unreachable(Exception):
    """Robinhood didn't answer or sent something that couldn't be read."""


def is_robinhood(server):
    return server.get("transport") == "http" and urlparse(server.get("url") or "").hostname == HOST


async def find_server():
    for server in await mcp_store.list_enabled_servers():
        if is_robinhood(server):
            return server
    return None


def read_result(text):
    """The answer is JSON followed by usage notes for a model, so only the leading JSON is read."""
    if not isinstance(text, str) or text.startswith("Error:"):
        raise Unreachable("Robinhood returned an error.")
    try:
        value, _ = json.JSONDecoder().raw_decode(text.lstrip())
    except ValueError as error:
        raise Unreachable("Robinhood sent an answer that couldn't be read.") from error
    if not isinstance(value, dict):
        raise Unreachable("Robinhood sent an answer that couldn't be read.")
    return value


def micro_to_dollars(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return (Decimal(value) / MICRO).quantize(Decimal("0.01"))


def read_transaction(item):
    """One purchase row, or None if Robinhood left out something needed."""
    if not isinstance(item, dict):
        return None
    merchant = (item.get("merchantDetails") or {}).get("merchantName")
    total = micro_to_dollars(item.get("amountMicro"))
    at = item.get("transactionAt")
    if not isinstance(item.get("id"), str) or not isinstance(merchant, str) or total is None or not isinstance(at, int):
        return None
    return {
        "purchase_id": item["id"],
        "merchant": merchant.strip()[:200] or "Unknown",
        "total": total,
        "status": str(item.get("transactionStatus") or "UNKNOWN")[:40],
        "decline_reason": item.get("declineReason") if isinstance(item.get("declineReason"), str) else None,
        "approval_status": item.get("declineAckStatus") if isinstance(item.get("declineAckStatus"), str) else None,
        "purchased_at": datetime.fromtimestamp(at / 1000, tz=timezone.utc),
    }


def read_card(status, balance):
    return {
        "active": status.get("activation") == "ACTIVATED" and status.get("cardStatus") == "NORMAL",
        "cardStatus": str(status.get("cardStatus") or "UNKNOWN"),
        "spentThisMonth": str(micro_to_dollars(balance.get("totalSpendMicro")) or Decimal("0.00")),
    }


async def call(session, name, arguments):
    return read_result(await session.call_tool(name, arguments))


async def read_card_activity(server):
    """Returns (card, transactions) from Robinhood."""
    session, tools = await toolbox.open_mcp_session(server)
    if session is None:
        raise Unreachable("Couldn't reach Robinhood. Try signing in again from the + menu.")
    try:
        status = await call(session, "banking_get_agent_card_status", {})
        balance = await call(session, "banking_get_agent_card_balance", {})
        transactions, cursor = [], None
        for _ in range(MAX_PAGES):
            arguments = {"limit": PAGE_SIZE, **({"cursor": cursor} if cursor else {})}
            page = ((await call(session, "banking_get_agent_card_transactions", arguments)).get("data") or {})
            search = page.get("transactionSearch") or {}
            items = search.get("items") or []
            transactions += [row for row in map(read_transaction, items) if row]
            cursor = search.get("cursor")
            if not items or not cursor:
                break
        return read_card(status, balance), transactions
    finally:
        await session.close()
