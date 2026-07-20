from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False


def setup_logging(logs_dir: Path, *, level: int = logging.INFO) -> None:
    """Konfiguriert App-weites Logging. Idempotent, damit main.py sie gefahrlos mehrfach aufrufen kann."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "app.log"

    root_logger = logging.getLogger("app")
    root_logger.setLevel(level)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"app.{name}")
