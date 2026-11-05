"""Makes macOS start the app and the Telegram bot at login, and restart them if they crash. Safe to run again:

    venv/bin/python -m scripts.install_autostart

This also puts back anything removed with the x button under ... > Auto Started Programs.
"""

import sys

from src.backend.autostart import service


def main():
    for label, program in service.PROGRAMS.items():
        try:
            service.install(label, sys.executable)
        except service.AutostartError as error:
            sys.exit(str(error))
        print(f"{program['name']} will start at login.")


if __name__ == "__main__":
    main()
