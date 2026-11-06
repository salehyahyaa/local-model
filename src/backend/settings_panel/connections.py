"""Everything connected to the app, for the Settings panel. Never includes a secret's value."""

from src.backend import config, db
from src.backend.autostart import service as autostart
from src.backend.chat import model_slot
from src.backend.integrations import service as integrations
from src.backend.secret_store import get_secret

TELEGRAM_LABEL = "com.localmodel.telegram-bot"


def model_status():
    model = model_slot.connected_model
    if model is None:
        return {"name": "Chat model", "detail": "No model connected", "isConnected": False}
    return {"name": "Chat model", "detail": getattr(model, "name", "Connected"), "isConnected": True}


def telegram_status():
    if not get_secret("TELEGRAM_BOT_TOKEN"):
        return {"name": "Telegram bot", "detail": "Not set up", "isConnected": False}
    is_running = autostart.is_running(TELEGRAM_LABEL)
    parts = ["Running" if is_running else "Not running"]
    if autostart.plist_path(TELEGRAM_LABEL).exists():
        parts.append("starts at login")
    return {"name": "Telegram bot", "detail": " · ".join(parts), "isConnected": is_running}


def voice_status():
    is_set_up = bool(config.DEEPGRAM_API_KEY)
    return {"name": "Voice input (Deepgram)", "detail": "API key saved" if is_set_up else "Not set up",
            "isConnected": is_set_up}


def image_status():
    has_model = config.IMAGE_MODEL_PATH.exists()
    return {"name": "Image generation", "detail": "Model file found" if has_model else "No model file",
            "isConnected": has_model}


def database_status():
    is_connected = db.pool is not None
    return {"name": "Database", "detail": "Connected" if is_connected else "Not connected", "isConnected": is_connected}


def app_autostart_status():
    starts_at_login = autostart.plist_path(autostart.APP_LABEL).exists()
    return {"name": "App auto-start", "detail": "Starts at login" if starts_at_login else "Off",
            "isConnected": starts_at_login}


def list_services():
    """Blocking: it reads the keychain and asks launchctl, so it runs on a worker thread."""
    return [model_status(), telegram_status(), voice_status(), image_status(), database_status(), app_autostart_status()]


def describe_integration(integration):
    return {"name": integration["name"], "detail": integration["target"], "isConnected": integration["enabled"]}


async def list_integrations():
    """Empty when the database is down, so the rest of the panel still shows."""
    try:
        saved = await integrations.list_integrations()
    except db.DatabaseUnavailableError:
        return []
    return [describe_integration(item) for item in [*saved["mcpServers"], *saved["apiIntegrations"]]]
