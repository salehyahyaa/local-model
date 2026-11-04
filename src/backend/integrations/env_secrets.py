import os
import re

from dotenv import dotenv_values, unset_key

from src.backend import config
from src.backend.secret_store import delete_secret, get_secret, set_secret

SECRET_PREFIX = "INTEGRATION_"
REFERENCE_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def to_slug(text):
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def secret_name(integration_name, purpose):
    return f"{SECRET_PREFIX}{to_slug(integration_name)}_{to_slug(purpose)}"


def reference(name):
    return "${" + name + "}"


def secret_exists(name):
    return bool(get_secret(name))


def save_secret(name, value):
    """Integration secrets go to the OS keychain, never to .env or the database."""
    set_secret(name, value)


def remove_secret(name):
    if not name.startswith(SECRET_PREFIX):
        return
    delete_secret(name)
    # Older integrations stored their secrets in .env; clean those up too.
    if config.ENV_FILE.exists() and name in dotenv_values(config.ENV_FILE):
        unset_key(str(config.ENV_FILE), name, quote_mode="always")
    os.environ.pop(name, None)


def resolve(text):
    return REFERENCE_PATTERN.sub(lambda match: get_secret(match.group(1)), text)


def resolve_mapping(mapping):
    return {key: resolve(value) for key, value in mapping.items()}


def find_references(mapping):
    names = set()
    for value in mapping.values():
        names.update(REFERENCE_PATTERN.findall(value))
    return names
