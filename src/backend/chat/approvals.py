"""Tool calls waiting for the owner's decision. Each id is random and can only be answered once."""

import asyncio
import secrets
from typing import NamedTuple

APPROVAL_TIMEOUT = 600

pending = {}


class Answer(NamedTuple):
    approved: bool
    follow_up: str | None = None


def create():
    approval_id = secrets.token_urlsafe(24)
    decision = asyncio.get_running_loop().create_future()
    pending[approval_id] = decision
    return approval_id, decision


def give_answer(approval_id, answer):
    decision = pending.pop(approval_id, None)
    if decision is None or decision.done():
        return False
    decision.set_result(answer)
    return True


def resolve(approval_id, approved):
    return give_answer(approval_id, Answer(approved))


def send_follow_up(approval_id, text):
    """The owner replied instead of tapping a button. A message never approves, whatever it says."""
    return give_answer(approval_id, Answer(False, text))


async def wait(approval_id, decision, timeout=None):
    """Anything except an explicit yes counts as no, including no answer in time."""
    try:
        return await asyncio.wait_for(decision, timeout or APPROVAL_TIMEOUT)
    except asyncio.TimeoutError:
        return Answer(False)
    finally:
        pending.pop(approval_id, None)
