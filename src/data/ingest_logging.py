"""File + console logging for ingest.py."""

from __future__ import annotations

import logging
import os
import sys

from core.config import BASE_DIR, LOGS_DIR

INGEST_LOG_PATH = os.environ.get(
    "INGEST_LOG_PATH", os.path.join(LOGS_DIR, "ingest.log")
)

_logger: logging.Logger | None = None


def setup_ingest_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    os.makedirs(LOGS_DIR, exist_ok=True)
    logger = logging.getLogger("pivony.ingest")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.FileHandler(INGEST_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    _logger = logger
    return logger
