# app/logging_config.py

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "mentalab-bridge.log"


def configure_logging() -> None:
    root_logger = logging.getLogger()

    # Avoid adding duplicate handlers when Uvicorn reloads.
    if getattr(root_logger, "_mentalab_configured", False):
        return

    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | "
        "%(name)s | %(threadName)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Terminal / console logs
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(formatter)

    # Persistent local log file
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    root_logger._mentalab_configured = True

    root_logger.info(
        "Mentalab Bridge logging initialized. Log file: %s",
        LOG_FILE,
    )