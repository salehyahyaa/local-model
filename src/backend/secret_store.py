"""Secrets (passwords, API keys) come from the OS keychain locally, or from environment variables in production.

Locally they're stored with `scripts/setup_db.py`, so their values never appear in .env or in any output.
"""

import logging
import os

import keyring
from keyring.errors import KeyringError

logger = logging.getLogger(__name__)

SERVICE_NAME = "local-model"


def keychain_enabled():
    """USE_KEYCHAIN=0 turns the keychain off (tests, servers that only use environment variables)."""
    return os.getenv("USE_KEYCHAIN", "1") != "0"


def get_secret(name):
    """An environment variable wins (production); otherwise the OS keychain. Returns "" if not set."""
    if os.getenv(name):
        return os.environ[name]
    if not keychain_enabled():
        return ""
    try:
        return keyring.get_password(SERVICE_NAME, name) or ""
    except KeyringError:
        logger.exception("Could not read %s from the OS keychain", name)
        return ""


def set_secret(name, value):
    if not keychain_enabled():
        os.environ[name] = value
        return
    keyring.set_password(SERVICE_NAME, name, value)


def delete_secret(name):
    if not keychain_enabled():
        os.environ.pop(name, None)
        return
    try:
        keyring.delete_password(SERVICE_NAME, name)
    except keyring.errors.PasswordDeleteError:
        pass
