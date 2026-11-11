"""Fernet encryption for the card. The key is in the OS keychain, so the database alone can't reveal the card."""

import json

from cryptography.fernet import Fernet, InvalidToken

from src.backend.secret_store import get_secret, set_secret

KEY_NAME = "AGENTIC_CARD_KEY"


class CardKeyMissing(Exception):
    """The encryption key isn't in the keychain, so the saved card can't be read."""


def get_or_create_key():
    key = get_secret(KEY_NAME)
    if not key:
        key = Fernet.generate_key().decode()
        set_secret(KEY_NAME, key)
    return key


def fernet(key=None):
    key = key or get_secret(KEY_NAME)
    if not key:
        raise CardKeyMissing("The card's encryption key is missing. Run scripts.setup_agentic_credit_card again.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_card(card, key=None):
    return fernet(key).encrypt(json.dumps(card).encode()).decode()


def decrypt_card(token, key=None):
    try:
        return json.loads(fernet(key).decrypt(token.encode()))
    except InvalidToken as error:
        raise CardKeyMissing("The saved card can't be decrypted with this key. Save the card again.") from error
