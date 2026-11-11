"""Stores the ElevenLabs webhook secret. Run it yourself, because the prompt is hidden:

    venv/bin/python -m scripts.setup_call_webhook

ElevenLabs shows the secret once, when you save the post-call webhook. It goes in the OS keychain and is never
printed. Safe to run again with a new secret.
"""

import getpass
import shlex
import sys

from src.backend.config import ROOT_DIR
from src.backend.secret_store import set_secret

SECRET_NAME = "ELEVENLABS_WEBHOOK_SECRET"


def main():
    secret = getpass.getpass("ElevenLabs webhook secret (hidden): ").strip()
    if not secret:
        print("Nothing entered; nothing was saved.")
        sys.exit(1)
    set_secret(SECRET_NAME, secret)
    print("Saved to the keychain.")
    print("Restart the app, then run the webhook server:")
    print(f"  cd {shlex.quote(str(ROOT_DIR))} && {shlex.quote(sys.executable)} -m src.backend.appointment_calls.webhook_server")


if __name__ == "__main__":
    main()
