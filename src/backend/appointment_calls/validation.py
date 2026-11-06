import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

PHONE_PATTERN = re.compile(r"^\+[1-9][0-9]{7,14}$")
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
NAME_MAX_LENGTH = 100
REASON_MAX_LENGTH = 500
MAX_SLOTS = 20
MAX_PARTY_SIZE = 100
RESERVATION = "reservation"
APPOINTMENT = "appointment"


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


def validate_call(arguments, now=None):
    """Returns (call, None) or (None, an error to show the model). The model's arguments are never trusted."""
    now = now or datetime.now(timezone.utc)
    kind = arguments.get("kind")
    if kind not in (RESERVATION, APPOINTMENT):
        return None, f"kind must be {RESERVATION} or {APPOINTMENT}."
    party_size = arguments.get("party_size")
    if kind == RESERVATION and not is_valid_party_size(party_size):
        return None, "party_size is missing. Ask the owner how many people before calling."
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
    return {
        "contact_name": contact_name,
        "phone_number": phone_number,
        "reason": reason,
        "booking_name": booking_name,
        "timezone": arguments["timezone"],
        "deadline": deadline,
        "allowed_slots": slots,
    }, None


def validate_connection(body):
    if not isinstance(body, dict):
        return None, "Invalid request."
    owner_name = clean_line(body.get("ownerName"), NAME_MAX_LENGTH)
    if owner_name is None:
        return None, "Enter the name the agent should say it's calling for."
    api_key = body.get("apiKey")
    if not isinstance(api_key, str) or not api_key.strip():
        return None, "Enter your ElevenLabs API key."
    agent_id = body.get("agentId")
    if not isinstance(agent_id, str) or not ID_PATTERN.match(agent_id.strip()):
        return None, "Enter your ElevenLabs agent ID."
    phone_number_id = body.get("phoneNumberId")
    if not isinstance(phone_number_id, str) or not ID_PATTERN.match(phone_number_id.strip()):
        return None, "Enter the phone number ID ElevenLabs gave your Twilio number."
    return {
        "owner_name": owner_name,
        "api_key": api_key.strip(),
        "agent_id": agent_id.strip(),
        "phone_number_id": phone_number_id.strip(),
    }, None
