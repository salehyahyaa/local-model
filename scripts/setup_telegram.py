"""One-time Telegram setup. Run it yourself, because the token prompt is hidden:

    venv/bin/python -m scripts.setup_telegram

First create a bot: in Telegram, message @BotFather, send /newbot, and copy the token it gives you.

What it does (safe to run again):
  1. Asks for the token and checks it with Telegram.
  2. Asks you to message the new bot, so it can learn your numeric Telegram ID.
  3. Stores the token and your ID in the OS keychain. The token is never printed.
  4. Prints the commands that run the bot, or start it at login. It doesn't run them.
"""

import asyncio
import getpass
import re
import shlex
import sys

from src.backend.config import ROOT_DIR
from src.backend.secret_store import set_secret
from src.backend.telegram_bot.telegram_api import TelegramApi, TelegramError, quiet_http_logs

TOKEN_FORMAT = re.compile(r"^\d+:[\w-]+$")
POLL_SECONDS = 30


def describe_sender(sender):
    name = " ".join(part for part in (sender.get("first_name"), sender.get("last_name")) if part)
    username = sender.get("username")
    return f"{name} (@{username})" if username else name


async def find_owner(telegram):
    """Keeps reading messages until the owner recognises themselves, and returns their ID."""
    offset = None
    while True:
        for update in await telegram.get_updates(offset=offset, timeout=POLL_SECONDS):
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            sender = message.get("from")
            if sender is None or (message.get("chat") or {}).get("type") != "private":
                continue
            answer = input(f"Message received from {describe_sender(sender)}. Is this you? [y/N] ")
            if answer.strip().lower() == "y":
                # Confirmed so the bot doesn't answer this setup message when it starts.
                await telegram.get_updates(offset=offset)
                return sender["id"]
            print("Not saved. Waiting for your message...")


async def set_up(token):
    telegram = TelegramApi(token)
    try:
        bot = await telegram.get_me()
        print(f"Token works for @{bot['username']}.")
        print(f"In Telegram, send @{bot['username']} any message. Waiting...")
        owner_id = await find_owner(telegram)
    finally:
        await telegram.close()
    set_secret("TELEGRAM_BOT_TOKEN", token)
    set_secret("TELEGRAM_OWNER_ID", str(owner_id))
    print("Token and owner ID stored in the keychain.")


def print_service_commands():
    print("\nTo try the bot now:\n")
    print(f"  cd {shlex.quote(str(ROOT_DIR))} && {shlex.quote(sys.executable)} -m src.backend.telegram_bot")
    print("\nTo start the app and the bot at login, and restart them after a crash:\n")
    print(f"  cd {shlex.quote(str(ROOT_DIR))} && {shlex.quote(sys.executable)} -m scripts.install_autostart")


def main():
    quiet_http_logs()
    token = getpass.getpass("Bot token from @BotFather (hidden): ").strip()
    if not TOKEN_FORMAT.match(token):
        sys.exit("That doesn't look like a bot token. Nothing was saved.")
    try:
        asyncio.run(set_up(token))
    except TelegramError as error:
        sys.exit(f"{error}. Nothing was saved.")
    except KeyboardInterrupt:
        sys.exit("\nCancelled. Nothing was saved.")
    print_service_commands()


if __name__ == "__main__":
    main()
