"""This project's programs that macOS starts at login, through launchd.

Only the programs named in PROGRAMS can be listed or removed, so nothing else on the Mac can be touched from here.
"""

import logging
import os
import plistlib
import subprocess
from pathlib import Path

from src.backend.config import ROOT_DIR

logger = logging.getLogger(__name__)

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LAUNCHCTL_TIMEOUT = 10
RESTART_DELAY_SECONDS = 30
NOT_LOADED_EXIT_CODE = 3

APP_LABEL = "com.localmodel.app"
PROGRAMS = {
    APP_LABEL: {
        "name": "Model app",
        "arguments": ["-m", "uvicorn", "src.backend.main:app", "--host", "127.0.0.1"],
    },
    "com.localmodel.telegram-bot": {
        "name": "Telegram bot",
        "arguments": ["-m", "src.backend.telegram_bot"],
    },
}


class AutostartError(Exception):
    """Its text is safe to show to the owner."""


def plist_path(label):
    return LAUNCH_AGENTS_DIR / f"{label}.plist"


def service_target(label):
    return f"gui/{os.getuid()}/{label}"


def run_launchctl(*arguments):
    return subprocess.run(["launchctl", *arguments], capture_output=True, text=True, timeout=LAUNCHCTL_TIMEOUT)


def is_running(label):
    try:
        result = run_launchctl("print", service_target(label))
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and any(line.strip() == "state = running" for line in result.stdout.splitlines())


def list_programs():
    return [
        {"id": label, "name": program["name"], "isRunning": is_running(label), "isThisApp": label == APP_LABEL}
        for label, program in PROGRAMS.items()
        if plist_path(label).exists()
    ]


def build_plist(label, python_path):
    return plistlib.dumps(
        {
            "Label": label,
            "ProgramArguments": [str(python_path), *PROGRAMS[label]["arguments"]],
            "WorkingDirectory": str(ROOT_DIR),
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": RESTART_DELAY_SECONDS,
        }
    )


def install(label, python_path):
    """Safe to run again: anything already installed under this label is replaced."""
    stop(label)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    path = plist_path(label)
    path.write_bytes(build_plist(label, python_path))
    result = run_launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
    if result.returncode != 0:
        raise AutostartError(f"macOS couldn't start {PROGRAMS[label]['name']} (launchctl exit {result.returncode}).")


def delete_plist(label):
    """Returns False if it wasn't installed. Without this file, the program won't start at the next login."""
    try:
        plist_path(label).unlink()
    except FileNotFoundError:
        return False
    return True


def stop(label):
    """Stops the program now and stops macOS restarting it. Stopping the app ends this process too."""
    try:
        result = run_launchctl("bootout", service_target(label))
    except (OSError, subprocess.SubprocessError) as error:
        logger.error("Could not stop %s: %s", label, type(error).__name__)
        return
    if result.returncode not in (0, NOT_LOADED_EXIT_CODE):
        logger.warning("launchctl couldn't stop %s (exit %s)", label, result.returncode)
