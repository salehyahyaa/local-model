"""Tool calls waiting for the owner's decision. Each id is random and can only be answered once."""

import asyncio
import secrets

APPROVAL_TIMEOUT = 600

pending = {}


def create():
    approval_id = secrets.token_urlsafe(24)
    decision = asyncio.get_running_loop().create_future()
    pending[approval_id] = decision
    return approval_id, decision


def resolve(approval_id, approved):
    decision = pending.pop(approval_id, None)
    if decision is None or decision.done():
        return False
    decision.set_result(approved)
    return True


async def wait(approval_id, decision):
    """Anything except an explicit yes counts as no, including no answer in time."""
    try:
        return await asyncio.wait_for(decision, APPROVAL_TIMEOUT)
    except asyncio.TimeoutError:
        return False
    finally:
        pending.pop(approval_id, None)
