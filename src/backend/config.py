"""App configuration, read from environment variables."""

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "src" / "frontend"
LOG_DIR = Path(os.getenv("LOG_DIR", ROOT_DIR / "logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:2b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))
