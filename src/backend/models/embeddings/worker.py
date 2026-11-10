"""Embeds one batch of texts in its own process, then exits so the model's memory is fully released.

Reads {"texts": [...], "cacheDir": "..."} as JSON on stdin and writes {"vectors": [[...], ...]} as JSON on stdout.
"""

import json
import sys


def main():
    job = json.load(sys.stdin)
    # Anything the libraries print goes to stderr, so stdout carries only the answer.
    answer = sys.stdout
    sys.stdout = sys.stderr
    from src.backend.models.embeddings import model

    vectors = model.embed(job["texts"], job["cacheDir"])
    json.dump({"vectors": vectors}, answer)
    answer.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
