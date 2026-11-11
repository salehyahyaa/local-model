"""Checks card details before they're saved. Nothing here ever logs or returns the full number."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_LIMIT = Decimal("50000")
NUMBER_PATTERN = re.compile(r"^[0-9]{13,19}$")
EXPIRY_PATTERN = re.compile(r"^(0[1-9]|1[0-2])/([0-9]{2})$")
CVV_PATTERN = re.compile(r"^[0-9]{3,4}$")
ZIP_PATTERN = re.compile(r"^[0-9]{5}$")


def passes_luhn(number):
    total = 0
    for position, digit in enumerate(int(d) for d in reversed(number)):
        if position % 2:
            digit = digit * 2 - 9 if digit > 4 else digit * 2
        total += digit
    return total % 10 == 0


def is_expired(expiry, today=None):
    month, year = EXPIRY_PATTERN.match(expiry).groups()
    today = today or date.today()
    return (2000 + int(year), int(month)) < (today.year, today.month)


def read_amount(value):
    """A positive dollar amount up to MAX_LIMIT, or None."""
    if isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).strip().lstrip("$").replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0 or amount > MAX_LIMIT:
        return None
    return amount.quantize(Decimal("0.01"))


def validate_card(number, expiry, cvv, zip_code):
    """Returns (card, None) or (None, error)."""
    number = re.sub(r"[ -]", "", number or "")
    expiry = (expiry or "").strip()
    if not NUMBER_PATTERN.match(number) or not passes_luhn(number):
        return None, "That card number isn't valid."
    if not EXPIRY_PATTERN.match(expiry):
        return None, "Expiry must look like MM/YY."
    if is_expired(expiry):
        return None, "That card has expired."
    if not CVV_PATTERN.match((cvv or "").strip()):
        return None, "CVV must be 3 or 4 digits."
    if not ZIP_PATTERN.match((zip_code or "").strip()):
        return None, "Billing ZIP must be 5 digits."
    return {"number": number, "expiry": expiry, "cvv": cvv.strip(), "zip": zip_code.strip()}, None
