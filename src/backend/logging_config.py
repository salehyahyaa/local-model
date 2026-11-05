import logging
import logging.config

from src.backend.config import LOG_DIR, LOG_LEVEL


def setup_logging(file_name="app.log"):
    """Each process needs its own file, because two processes rotating the same log file would corrupt it."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                }
            },
            "handlers": {
                "console": {"class": "logging.StreamHandler", "formatter": "default"},
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "default",
                    "filename": str(LOG_DIR / file_name),
                    "maxBytes": 5_000_000,
                    "backupCount": 3,
                    "encoding": "utf-8",
                },
            },
            "root": {"level": LOG_LEVEL, "handlers": ["console", "file"]},
        }
    )
