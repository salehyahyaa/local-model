"""Stands in for the embedding worker: answers like the real one, with made-up numbers. No model involved."""

import json
import os
import sys

from src.backend.models.embeddings import DIMENSIONS

PID_FILE_ENV = "FAKE_EMBEDDING_WORKER_PID_FILE"


def fake_vector(text):
    seed = sum(ord(character) for character in text)
    return [((seed * (index + 1)) % 97) / 97 for index in range(DIMENSIONS)]


def main():
    job = json.load(sys.stdin)
    pid_file = os.getenv(PID_FILE_ENV)
    if pid_file:
        with open(pid_file, "w") as output:
            output.write(str(os.getpid()))
    if any(text == "crash" for text in job["texts"]):
        sys.exit(3)
    json.dump({"vectors": [fake_vector(text) for text in job["texts"]]}, sys.stdout)


if __name__ == "__main__":
    main()
