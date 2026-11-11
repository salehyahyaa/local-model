import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
NAME_MAX_LENGTH = 100
REASON_MAX_LENGTH = 500
MAX_SLOTS = 20
MAX_PARTY_SIZE = 100
MAX_ORDER_ITEMS = 30
ORDER_ITEM_MAX_LENGTH = 200
IF_UNAVAILABLE_MAX_LENGTH = 300
RESERVATION = "reservation"
APPOINTMENT = "appointment"
PICKUP_ORDER = "pickup_order"
KINDS = (RESERVATION, APPOINTMENT, PICKUP_ORDER)


def clean_line(value, max_length):
    """These values go into the agent's prompt, so they're kept to one line."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text if text and len(text) <= max_length else None


def read_time(value):
    """Only times that say their UTC offset are accepted, so "2pm" can't silently mean the wrong hour."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def read_timezone(value):
    if not isinstance(value, str):
        return None
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def validate_slots(slots, deadline, now):
    if not isinstance(slots, list) or not 1 <= len(slots) <= MAX_SLOTS:
        return None, f"allowed_slots needs 1 to {MAX_SLOTS} time ranges."
    cleaned = []
    for slot in slots:
        start = read_time(slot.get("start")) if isinstance(slot, dict) else None
        end = read_time(slot.get("end")) if isinstance(slot, dict) else None
        if start is None or end is None:
            return None, "Each slot needs start and end as ISO 8601 times with a UTC offset."
        if start >= end:
            return None, "Each slot must start before it ends."
        if end <= now:
            return None, "Every slot must still be in the future."
        if end > deadline:
            return None, "Every slot must end by the deadline."
        cleaned.append({"start": start.isoformat(), "end": end.isoformat()})
    return cleaned, None


def is_valid_party_size(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= MAX_PARTY_SIZE


def validate_order_items(items):
    """A pickup order is only placed with the owner's own list; the agent must never decide what to order."""
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ORDER_ITEMS:
        return None
    cleaned = [clean_line(item, ORDER_ITEM_MAX_LENGTH) for item in items]
    return cleaned if all(cleaned) else None


def validate_call(arguments, now=None):
    """Returns (call, None) or (None, an error to show the model). The model's arguments are never trusted."""
    now = now or datetime.now(timezone.utc)
    kind = arguments.get("kind")
    if kind not in KINDS:
        return None, f"kind must be one of: {', '.join(KINDS)}."
    party_size = arguments.get("party_size")
    if kind == RESERVATION and not is_valid_party_size(party_size):
        return None, "party_size is missing. Ask the owner how many people before calling."
    order_items = None
    if kind == PICKUP_ORDER:
        order_items = validate_order_items(arguments.get("order_items"))
        if order_items is None:
            return None, "order_items is missing. Ask the owner exactly what to order before calling. Never guess."
    if_unavailable = arguments.get("if_unavailable")
    if if_unavailable is None:
        if_unavailable = ""
    else:
        if_unavailable = clean_line(if_unavailable, IF_UNAVAILABLE_MAX_LENGTH)
        if if_unavailable is None:
            return None, f"if_unavailable must be up to {IF_UNAVAILABLE_MAX_LENGTH} characters."
    booking_name = arguments.get("booking_name")
    if booking_name is not None:
        booking_name = clean_line(booking_name, NAME_MAX_LENGTH)
        if booking_name is None:
            return None, f"booking_name must be up to {NAME_MAX_LENGTH} characters."
    contact_name = clean_line(arguments.get("contact_name"), NAME_MAX_LENGTH)
    if contact_name is None:
        return None, f"contact_name is required (up to {NAME_MAX_LENGTH} characters)."
    phone_number = arguments.get("phone_number")
    if not isinstance(phone_number, str) or not PHONE_PATTERN.match(phone_number):
        return None, "phone_number must be in international format, like +14155550123."
    reason = clean_line(arguments.get("reason"), REASON_MAX_LENGTH)
    if reason is None:
        return None, f"reason is required (up to {REASON_MAX_LENGTH} characters)."
    if read_timezone(arguments.get("timezone")) is None:
        return None, "timezone must be an IANA name, like America/New_York."
    deadline = read_time(arguments.get("deadline"))
    if deadline is None:
        return None, "deadline must be an ISO 8601 time with a UTC offset."
    if deadline <= now:
        return None, "deadline must be in the future."
    slots, error = validate_slots(arguments.get("allowed_slots"), deadline, now)
    if error:
        return None, error
    if kind == RESERVATION:
        reason = f"{reason} Party of {party_size}."
    if kind == PICKUP_ORDER:
        reason = f"{reason} Pickup order: {'; '.join(order_items)}."
    return {
        "kind": kind,
        "if_unavailable": if_unavailable,
        "contact_name": contact_name,
        "phone_number": phone_number,
        "reason": reason,
        "booking_name": booking_name,
        "timezone": arguments["timezone"],
        "deadline": deadline,
        "allowed_slots": slots,
    }, None

