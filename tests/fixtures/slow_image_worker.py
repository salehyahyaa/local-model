"""Stands in for the image worker: takes a few seconds, then writes its files. No model involved."""

import json
import os
import sys
import time

GENERATION_SECONDS = 4
PID_FILE_ENV = "SLOW_WORKER_PID_FILE"


def main():
    job = json.load(sys.stdin)
    pid_file = os.getenv(PID_FILE_ENV)
    if pid_file:
        with open(pid_file, "w") as output:
            output.write(str(os.getpid()))
    time.sleep(GENERATION_SECONDS)
    for path in job["outputPaths"]:
        with open(path, "wb") as output:
            output.write(b"png")


if __name__ == "__main__":
    main()
