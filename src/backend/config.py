import os
from pathlib import Path

from dotenv import load_dotenv

from src.backend.secret_store import get_secret

ROOT_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = Path(os.getenv("ENV_FILE", ROOT_DIR / ".env"))
load_dotenv(ENV_FILE)

FRONTEND_DIR = ROOT_DIR / "src" / "frontend"
LOG_DIR = Path(os.getenv("LOG_DIR", ROOT_DIR / "logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

DEEPGRAM_API_KEY = get_secret("DEEPGRAM_API_KEY")
DEEPGRAM_MODEL = os.getenv("DEEPGRAM_MODEL", "nova-3")
DEEPGRAM_TIMEOUT = float(os.getenv("DEEPGRAM_TIMEOUT", "30"))

DATABASE_URL = os.getenv("DATABASE_URL", "")  # optional full URL; overrides the settings below
DATABASE_HOST = os.getenv("DATABASE_HOST", "localhost")
DATABASE_PORT = int(os.getenv("DATABASE_PORT", "5432"))
DATABASE_NAME = os.getenv("DATABASE_NAME", "local-model")
DATABASE_USER = os.getenv("DATABASE_USER", "local_model_app")  # read/write rows only
DATABASE_PASSWORD = get_secret("DATABASE_PASSWORD")
DATABASE_OWNER_USER = os.getenv("DATABASE_OWNER_USER", "local_model_owner")  # owns tables, runs migrations

IMAGE_MODEL_PATH = Path(
    os.getenv("IMAGE_MODEL_PATH", Path.home() / "Desktop" / "models4System" / "RealVisXL_V5.0_fp16_imgGen.safetensors")
)
IMAGE_DIR = Path(os.getenv("IMAGE_DIR", ROOT_DIR / "data" / "images"))
IMAGE_TIMEOUT = float(os.getenv("IMAGE_TIMEOUT", "1800"))

TOOL_TIMEOUT = float(os.getenv("TOOL_TIMEOUT", "30"))
MAX_TOOL_RESULT_CHARACTERS = int(os.getenv("MAX_TOOL_RESULT_CHARACTERS", "8000"))

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", ROOT_DIR / "data" / "uploads"))
MAX_DOCUMENT_BYTES = int(os.getenv("MAX_DOCUMENT_BYTES", str(20 * 1024 * 1024)))

TELEGRAM_BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN")
TELEGRAM_OWNER_ID = get_secret("TELEGRAM_OWNER_ID")
TELEGRAM_CHAT_TIMEOUT = float(os.getenv("TELEGRAM_CHAT_TIMEOUT", "1800"))
APP_URL = os.getenv("APP_URL", "http://127.0.0.1:8000")

ELEVENLABS_API_URL = os.getenv("ELEVENLABS_API_URL", "https://api.elevenlabs.io")
ELEVENLABS_TIMEOUT = float(os.getenv("ELEVENLABS_TIMEOUT", "10"))
APPOINTMENT_CALL_RESULT_TIMEOUT = float(os.getenv("APPOINTMENT_CALL_RESULT_TIMEOUT", "1800"))
APPOINTMENT_CALL_POLL_SECONDS = float(os.getenv("APPOINTMENT_CALL_POLL_SECONDS", "15"))
TASK_SCAN_SECONDS = float(os.getenv("TASK_SCAN_SECONDS", "300"))
TASK_MODEL_EMAILS_PER_SCAN = int(os.getenv("TASK_MODEL_EMAILS_PER_SCAN", "100"))
